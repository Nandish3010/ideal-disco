"""Cop voice back-channel: POST /cop-note and the rules that act on the extracted note (copnote.apply)."""

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

import copnote
import main
import ratelimit
from fakefs import FakeFirestore
from gemini import ExtractionFailed
from test_api import AMB, FIRE, alerting_run, assert_envelope
from test_tokens import bind, hdr


class Scene:
    """A scenario ambulance with one alert at `jid`, a green phase running there, and a cop on duty."""

    def __init__(self, client: TestClient, db: FakeFirestore) -> None:
        self.client, self.db = client, db
        self.rid, n = alerting_run(client, db)
        self.alert = db.collection("runs").document(self.rid).collection("alerts").document(str(n))
        self.jid: str = self.alert.get().to_dict()["junction_id"]
        assert self.jid in (db.collection("runs").document(self.rid).get().to_dict() or {})["ahead_ids"]
        self.junction = db.collection("junctions").document(self.jid)
        assert (self.junction.get().to_dict() or {})["phase"]["until"] > datetime.now(UTC)
        self.token = client.post(
            "/duty", json={"corridor": "blr", "junction_id": self.jid, "device_id": "cop-1", "on": True}
        ).json()["device_token"]

    def say(self, text: str, **kw: Any) -> dict:
        r = self.client.post(
            "/cop-note",
            json={"corridor": "blr", "junction_id": self.jid, "text": text, **kw},
            headers=hdr(self.token),
        )
        assert r.status_code == 200, r.text
        return r.json()

    def apply(self, **raw: Any) -> dict:
        return copnote.apply(
            self.db, self.jid, {"reason": "r", "transcript_en": "t", **raw}, datetime.now(UTC)
        )

    @property
    def a(self) -> dict:
        return self.alert.get().to_dict() or {}

    @property
    def until(self) -> datetime:
        return (self.junction.get().to_dict() or {})["phase"]["until"]

    def audit(self, action: str) -> list[dict]:
        return [d.to_dict() for d in self.db.collection("audit").stream() if d.to_dict()["action"] == action]


@pytest.fixture
def scene(client: TestClient, seeded: FakeFirestore) -> Scene:
    return Scene(client, seeded)


# ---- delay ------------------------------------------------------------------------------------------------------------


def test_a_stalled_bus_extends_the_green_and_escalates(scene: Scene) -> None:
    before = scene.until
    out = scene.say("a bus has stalled in the junction")
    assert (out["kind"], out["extra_seconds"], out["reason"]) == ("delay", 120, "bus stalled")
    assert (
        out["action_text"] == "Green extended by 2 min, escalated"
        and out["effects"]["phase_extended_s"] == 120
    )
    assert scene.until - before == timedelta(seconds=120)
    a = scene.a
    assert (
        a["cop_delay_s"] == 120
        and a["cop_note"]["reason"] == "bus stalled"
        and a["cop_note"]["extra_seconds"] == 120
    )
    assert a["escalated"] is True and a["escalation_reason"] == "cop_reported_delay" and a["escalated_at"]
    (d,) = scene.audit("cop_delay")
    assert (d["junction_id"], d["extra_seconds"], d["reason"], d["run_ids"]) == (
        scene.jid,
        120,
        "bus stalled",
        [scene.rid],
    )
    (e,) = scene.audit("escalation")  # counted in the run report like a timed escalation
    assert (e["run_id"], e["alert_n"], e["reason"]) == (scene.rid, int(scene.alert.id), "cop_reported_delay")
    note = scene.db.collection("duty").document(scene.jid).collection("notes").document("0").get().to_dict()
    assert note["kind"] == "delay" and note["transcript_en"] and note["device_id"] == "cop-1"


def test_a_short_delay_extends_but_does_not_escalate(scene: Scene) -> None:
    before = scene.until
    out = scene.apply(kind="delay", extra_seconds=90)
    assert out["effects"] == {"phase_extended_s": 90, "acked": 0, "escalated": 0, "blocked_s": 0}
    assert out["action_text"] == "Green extended by 90 s"
    assert scene.until - before == timedelta(seconds=90) and scene.a["escalated"] is False


def test_delays_are_capped_defaulted_and_cumulative(scene: Scene) -> None:
    before = scene.until
    assert scene.apply(kind="delay", extra_seconds=900)["extra_seconds"] == 180
    assert scene.apply(kind="delay", extra_seconds=None)["extra_seconds"] == 60
    assert scene.apply(kind="delay", extra_seconds=-5)["extra_seconds"] == 60
    assert scene.until - before == timedelta(seconds=300)
    assert scene.a["cop_delay_s"] == 300
    assert (
        scene.audit("escalation") != [] and len(scene.audit("escalation")) == 1
    )  # the alert is flagged once


def test_a_delay_with_no_green_running_is_noted_only(scene: Scene) -> None:
    scene.junction.update({"phase": None})
    out = scene.apply(kind="delay", extra_seconds=100)
    assert out["effects"]["phase_extended_s"] == 0
    assert out["action_text"] == "Delay of 100 s noted, no green to extend, escalated"
    scene.junction.update({"phase": {"approach": "E", "until": datetime.now(UTC) - timedelta(seconds=5)}})
    scene.apply(kind="delay", extra_seconds=100)
    assert scene.junction.get().to_dict()["phase"]["until"] < datetime.now(UTC)  # a stale phase stays stale


def test_a_long_delay_never_escalates_an_alert_that_is_already_acked(scene: Scene) -> None:
    scene.alert.update({"acked_at": datetime.now(UTC)})
    out = scene.apply(kind="delay", extra_seconds=150)
    assert out["effects"]["escalated"] == 0 and out["effects"]["phase_extended_s"] == 150
    assert scene.a["escalated"] is False and scene.audit("escalation") == []
    assert scene.a["cop_delay_s"] == 150  # still noted on the alert


def test_a_long_delay_escalates_only_the_unacked_alert_of_a_run_still_approaching(scene: Scene) -> None:
    runs = scene.db.collection("runs")
    other = runs.document("run-ahead")  # a second run still heading for the junction: its alert is unacked
    other.set(
        {**(runs.document(scene.rid).get().to_dict() or {}), "ahead_ids": [scene.jid], "state": "en_route"}
    )
    mine = other.collection("alerts").document("0")
    mine.set(
        {"junction_id": scene.jid, "stage": "PREPARE", "created_at": datetime.now(UTC), "acked_at": None}
    )
    gone = runs.document("run-passed")  # a run that already passed: state en_route but no longer ahead
    gone.set({"vehicle_type": "ambulance", "state": "en_route", "ahead_ids": []})
    old = gone.collection("alerts").document("0")
    old.set({"junction_id": scene.jid, "stage": "STOP", "created_at": datetime.now(UTC), "acked_at": None})
    scene.alert.update({"acked_at": datetime.now(UTC)})
    out = scene.apply(kind="delay", extra_seconds=150)
    assert out["effects"]["escalated"] == 1
    assert mine.get().to_dict()["escalated"] is True and mine.get().to_dict()["escalation_reason"]
    assert scene.a["escalated"] is False and "cop_note" in scene.a
    assert not old.get().to_dict().get("escalated") and "cop_note" not in old.get().to_dict()


# ---- cleared ----------------------------------------------------------------------------------------------------------


def test_cleared_acks_the_newest_unacked_alert(scene: Scene) -> None:
    run = scene.db.collection("runs").document(scene.rid)
    older = run.collection("alerts").document("99")
    older.set({**scene.a, "created_at": datetime.now(UTC) - timedelta(seconds=30), "acked_at": None})
    scene.alert.update({"created_at": datetime.now(UTC) - timedelta(seconds=8)})
    out = scene.say("junction is clear now")
    assert (
        out["kind"] == "cleared"
        and out["action_text"] == "Alert acknowledged"
        and out["effects"]["acked"] == 1
    )
    a = scene.a
    assert a["acked_at"] and a["acked_by"] == "cop-note" and 7 <= a["ack_latency_s"] < 10
    assert (older.get().to_dict() or {})["acked_at"] is None  # only the newest
    assert [d["junction_id"] for d in scene.audit("cop_cleared")] == [scene.jid]
    assert scene.say("all clear")["action_text"] == "Alert acknowledged"  # now the older one
    assert scene.say("all clear")["action_text"] == "Junction clear noted, no open alert"


def test_an_acked_alert_by_note_is_never_escalated(scene: Scene) -> None:
    scene.say("clear")
    scene.alert.update({"created_at": datetime.now(UTC) - timedelta(seconds=60)})
    assert main.escalate(datetime.now(UTC), [scene.rid], []) == 0


# ---- cannot_clear and other ---------------------------------------------------------------------------------------------


def test_cannot_clear_escalates_and_blocks_the_junction(scene: Scene) -> None:
    out = scene.apply(kind="cannot_clear", reason="crowd on the road")
    assert out["effects"]["escalated"] == 1 and out["effects"]["blocked_s"] == 300
    assert scene.a["escalated"] is True and scene.a["escalation_reason"] == "cop_cannot_clear"
    j = scene.junction.get().to_dict() or {}
    assert j["phase"]["blocked"] is True and main.cop_blocked(scene.jid, datetime.now(UTC))
    assert not main.cop_blocked(scene.jid, datetime.now(UTC) + timedelta(seconds=301))
    assert [d["reason"] for d in scene.audit("cop_cannot_clear")] == ["crowd on the road"]
    assert scene.audit("escalation")[0]["reason"] == "cop_cannot_clear"


def test_cannot_clear_without_a_phase_still_blocks(scene: Scene) -> None:
    scene.junction.update({"phase": None})
    scene.apply(kind="cannot_clear")
    j = scene.junction.get().to_dict() or {}
    assert j["phase"] is None and main.cop_blocked(scene.jid, datetime.now(UTC))  # no stub phase is invented


def test_a_blocked_junction_is_cleared_for_twice_as_long(scene: Scene) -> None:
    plain = scene.until
    assert (scene.junction.get().to_dict() or {})["phase"]["blocked"] is False
    # the same scenario run again, with every junction reported blocked: its phase is requested earlier and held longer
    for j in scene.db.collection("junctions").stream():
        j.reference.update({"cop_block_until": datetime.now(UTC) + timedelta(seconds=300), "phase": None})
    rid, n = alerting_run(scene.client, scene.db)
    assert rid != scene.rid
    phase = (scene.junction.get().to_dict() or {})["phase"]
    assert phase["blocked"] is True and phase["until"] - plain > timedelta(seconds=15)


def test_an_expired_block_changes_nothing(scene: Scene) -> None:
    for j in scene.db.collection("junctions").stream():
        j.reference.update({"cop_block_until": datetime.now(UTC) - timedelta(seconds=1), "phase": None})
    alerting_run(scene.client, scene.db)
    assert (scene.junction.get().to_dict() or {})["phase"]["blocked"] is False


def test_other_is_noted_and_audited_only(scene: Scene) -> None:
    before = scene.until
    out = scene.apply(kind="other", extra_seconds=50, reason="rain starting")
    assert out["action_text"] == "Noted" and out["extra_seconds"] is None
    a = scene.a
    assert a["acked_at"] is None and a["escalated"] is False and "cop_delay_s" not in a
    assert a["cop_note"]["kind"] == "other" and scene.until == before
    assert [d["reason"] for d in scene.audit("cop_note")] == ["rain starting"]


def test_an_unknown_kind_is_other_and_text_is_trimmed(scene: Scene) -> None:
    out = scene.apply(kind="launch_missiles", reason=" " + "x" * 200, transcript_en="y" * 900)
    assert out["kind"] == "other" and len(out["reason"]) == 80 and len(out["transcript_en"]) == 500


def test_notes_are_numbered_and_survive_going_on_duty_again(scene: Scene) -> None:
    scene.say("clear")
    scene.say("bus")
    again = scene.client.post(
        "/duty", json={"corridor": "blr", "junction_id": scene.jid, "device_id": "cop-2", "on": True}
    )
    assert again.status_code == 200
    scene.token = again.json()["device_token"]
    assert scene.say("clear")["n"] == 2
    notes = scene.db.collection("duty").document(scene.jid).collection("notes")
    assert sorted(d.id for d in notes.stream()) == ["0", "1", "2"]


def test_only_alerts_of_runs_still_heading_there_are_touched(scene: Scene) -> None:
    scene.db.collection("runs").document(scene.rid).update({"ahead_ids": []})  # it has passed the junction
    out = scene.apply(kind="delay", extra_seconds=120)
    assert out["effects"]["escalated"] == 0 and "cop_note" not in scene.a
    assert out["effects"]["phase_extended_s"] == 120  # the green is still extended


# ---- the endpoint -----------------------------------------------------------------------------------------------------


def test_audio_is_accepted_and_input_is_checked(scene: Scene) -> None:
    clip = base64.b64encode(b"\x00\x01").decode()
    assert scene.say("", audio_b64=clip, mime="audio/webm")["kind"] == "cleared"  # OFFLINE_AI stub: no "bus"
    body = {"corridor": "blr", "junction_id": scene.jid}
    h = hdr(scene.token)
    assert_envelope(scene.client.post("/cop-note", json=body, headers=h), 400, "bad_request")
    assert_envelope(
        scene.client.post("/cop-note", json={**body, "audio_b64": "!!"}, headers=h), 400, "bad_request"
    )
    bad = {"corridor": "mars", "junction_id": "j1", "text": "x"}
    assert_envelope(scene.client.post("/cop-note", json=bad, headers=h), 400, "unknown_corridor")
    assert_envelope(
        scene.client.post("/cop-note", json={**bad, "corridor": "blr", "junction_id": "j99"}, headers=h),
        404,
        "unknown_junction",
    )


def test_a_failed_extraction_is_422_and_changes_nothing(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: Any) -> dict:
        raise ExtractionFailed("x")

    monkeypatch.setattr(main.gemini, "cop_note", fail)
    r = scene.client.post(
        "/cop-note",
        json={"corridor": "blr", "junction_id": scene.jid, "text": "bus"},
        headers=hdr(scene.token),
    )
    assert assert_envelope(r, 422, "extraction_failed")["fallback"] == "text"
    assert "cop_note" not in scene.a and scene.audit("cop_delay") == []


def test_cop_note_needs_the_on_duty_cops_token(scene: Scene, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEVICE_TOKENS_DISABLED")
    body = {"corridor": "blr", "junction_id": scene.jid, "text": "bus"}
    post = lambda token: scene.client.post("/cop-note", json=body, headers=hdr(token))  # noqa: E731
    assert_envelope(post(None), 401, "device_token_required")
    assert_envelope(post("nope"), 403, "device_token_mismatch")
    assert_envelope(post(bind(scene.client, AMB)), 403, "device_token_mismatch")  # a vehicle is not a cop
    assert_envelope(post(bind(scene.client, FIRE)), 403, "device_token_mismatch")
    elsewhere = scene.client.post(
        "/duty",
        json={
            "corridor": "blr",
            "junction_id": "j5" if scene.jid != "blr_j5" else "j4",
            "device_id": "c",
            "on": True,
        },
    ).json()["device_token"]
    assert_envelope(post(elsewhere), 403, "device_token_mismatch")  # another junction's cop
    assert post(scene.token).status_code == 200
    off = {"corridor": "blr", "junction_id": scene.jid, "device_id": "cop-1", "on": False}
    assert scene.client.post("/duty", json=off, headers=hdr(scene.token)).status_code == 200
    assert_envelope(post(scene.token), 403, "device_token_mismatch")  # off duty


def test_cop_note_shares_the_heavy_rate_budget() -> None:
    assert ratelimit.kind("/cop-note") == "heavy" and ratelimit.PER_MIN["heavy"] == 10


def test_a_note_for_a_junction_nobody_is_on_duty_at_works_with_tokens_off(
    client: TestClient, seeded: FakeFirestore
) -> None:
    r = client.post("/cop-note", json={"corridor": "blr", "junction_id": "j2", "text": "all clear"})
    assert (
        r.status_code == 200 and r.json()["n"] == 0 and r.json()["action_text"].startswith("Junction clear")
    )
