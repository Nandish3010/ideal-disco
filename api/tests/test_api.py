"""Endpoint contracts through TestClient: OFFLINE_AI=1, in-memory Firestore, no network."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import ServiceUnavailable
from httpx import Response

import main
import priority
from fakefs import FakeFirestore

AMB = "KA01AB1234"
FIRE = "KA01FE5678"
BLR_HOSPITAL = {"name": "Jayadeva Institute of Cardiovascular Sciences", "lat": 12.9185, "lng": 77.599}


def new_incident(client: TestClient, kind: str = "cardiac") -> str:
    return client.post("/incidents", json={"type": kind}).json()["incident_id"]


def start(client: TestClient, plate: str = AMB, **kw: object) -> str:
    body = {"action": "start", "plate": plate, "incident_id": new_incident(client), "corridor": "blr", **kw}
    r = client.post("/runs", json=body)
    assert r.status_code == 200, r.text
    return r.json()["run_id"]


def run_doc(db: FakeFirestore, rid: str) -> dict:
    return db.collection("runs").document(rid).get().to_dict() or {}


def assert_envelope(r: Response, status: int, code: str) -> dict:
    assert r.status_code == status, r.text
    body = r.json()
    assert body["error"] == code and isinstance(body["detail"], str) and body["detail"]
    return body


# ---- plumbing: health, request id, envelope, CORS --------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_request_id_is_echoed_or_generated(client: TestClient) -> None:
    assert client.get("/health", headers={"X-Request-Id": "abc-123"}).headers["X-Request-Id"] == "abc-123"
    generated = client.get("/health").headers["X-Request-Id"]
    assert len(generated) == 36 and generated != client.get("/health").headers["X-Request-Id"]


def test_request_id_is_on_every_log_line(client: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
    client.post("/vehicles/bind", json={"plate": "NOPE", "device_id": "d"}, headers={"X-Request-Id": "req-9"})
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert {"bind_rejected", "request"} <= {__import__("json").loads(line)["event"] for line in lines}
    assert all(__import__("json").loads(line)["request_id"] == "req-9" for line in lines)


def test_error_envelope_for_unknown_route_and_bad_body(client: TestClient) -> None:
    assert_envelope(client.get("/nope"), 404, "not_found")
    assert_envelope(client.get("/runs"), 405, "method_not_allowed")
    body = assert_envelope(
        client.post("/location", json={"run_id": "r", "lat": 999, "lng": 0, "speed_mps": 1}),
        422,
        "validation_error",
    )
    assert "lat" in body["detail"]
    assert "X-Request-Id" in client.get("/nope").headers


def test_unexpected_errors_become_500_and_store_errors_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        def __init__(self, exc: Exception):
            self.exc = exc

        def collection(self, name: str) -> None:
            raise self.exc

    monkeypatch.setattr(main, "db", Broken(RuntimeError("boom")))
    r = client.post("/incidents", json={"type": "cardiac"})
    assert_envelope(r, 500, "internal_error")
    assert "boom" not in r.text and r.headers["X-Request-Id"]
    monkeypatch.setattr(main, "db", Broken(ServiceUnavailable("down")))
    assert_envelope(client.post("/incidents", json={"type": "cardiac"}), 503, "store_unavailable")
    monkeypatch.setattr(main, "db", Broken(RuntimeError("boom")))
    r = client.post("/incidents", json={"type": "cardiac"}, headers={"Origin": "http://localhost:5173"})
    assert (
        r.status_code == 500 and r.headers["access-control-allow-origin"] == "http://localhost:5173"
    )  # the browser can read it


def test_cors_allows_only_known_origins(client: TestClient) -> None:
    def preflight(origin: str) -> Response:
        return client.options(
            "/incidents",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    for ok in (
        "https://green-corridor-2026.web.app",
        "https://green-corridor-2026.firebaseapp.com",
        "http://localhost:5173",
    ):
        assert preflight(ok).headers["access-control-allow-origin"] == ok
    assert "access-control-allow-origin" not in preflight("https://evil.example").headers


# ---- vehicles, incidents ---------------------------------------------------------------------------------------------


def test_bind_unknown_is_404(client: TestClient, seeded: FakeFirestore) -> None:
    assert_envelope(
        client.post("/vehicles/bind", json={"plate": "XX00XX0000", "device_id": "d1"}),
        404,
        "unregistered_vehicle",
    )


def test_bind_inactive_is_404(client: TestClient, seeded: FakeFirestore) -> None:
    seeded.collection("vehicles").document(AMB).update({"active": False})
    assert client.post("/vehicles/bind", json={"plate": AMB, "device_id": "d1"}).status_code == 404


def test_bind_known(client: TestClient, seeded: FakeFirestore) -> None:
    r = client.post("/vehicles/bind", json={"plate": AMB, "device_id": "d1"})
    assert r.status_code == 200 and r.json()["bound_device_id"] == "d1" and r.json()["type"] == "ambulance"
    assert seeded.collection("vehicles").document(AMB).get().to_dict()["bound_device_id"] == "d1"


def test_incident_created_open(client: TestClient, db: FakeFirestore) -> None:
    iid = new_incident(client)
    assert iid.startswith("INC-") and len(iid) == 10
    assert db.collection("incidents").document(iid).get().to_dict()["state"] == "open"


# ---- runs ------------------------------------------------------------------------------------------------------------


def test_start_needs_all_fields(client: TestClient) -> None:
    assert_envelope(client.post("/runs", json={"action": "start", "plate": AMB}), 400, "bad_request")
    assert_envelope(client.post("/runs", json={"action": "pause"}), 400, "bad_request")


def test_start_403_unregistered_vehicle(client: TestClient, seeded: FakeFirestore) -> None:
    body = {"action": "start", "plate": "XX", "incident_id": new_incident(client), "corridor": "blr"}
    assert_envelope(client.post("/runs", json=body), 403, "unregistered_vehicle")


def test_start_403_no_active_incident(client: TestClient, seeded: FakeFirestore) -> None:
    body = {"action": "start", "plate": AMB, "incident_id": "INC-NOPE", "corridor": "blr"}
    assert_envelope(client.post("/runs", json=body), 403, "no_active_incident")
    iid = new_incident(client)
    seeded.collection("incidents").document(iid).update({"state": "closed"})
    assert client.post("/runs", json={**body, "incident_id": iid}).status_code == 403


def test_start_200_stores_the_scenario(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client, scenario="blr-two-vehicles", source="sim", destination=BLR_HOSPITAL)
    run = run_doc(seeded, rid)
    assert rid.startswith("run-") and run["state"] == "en_route" and run["patient_on_board"] is False
    assert (
        run["scenario"] == "blr-two-vehicles"
        and run["vehicle_type"] == "ambulance"
        and run["destination"] == BLR_HOSPITAL
    )
    assert "scenario" not in run_doc(seeded, start(client, plate=FIRE))


def test_starting_again_supersedes_the_active_run(client: TestClient, seeded: FakeFirestore) -> None:
    first = start(client)
    other = start(client, plate="KA01AB4321")
    seeded.collection("runs").document(first).update(
        {"state": "off_route", "ahead_ids": ["blr_j1"], "ahead": {"blr_j1": {}}}
    )
    done = start(client)  # supersedes `first`
    seeded.collection("runs").document(done).update({"state": "arrived"})  # already finished: left alone
    second = start(client)

    old = run_doc(seeded, first)
    assert (old["state"], old["ended_reason"], old["ahead_ids"], old["ahead"]) == (
        "ended",
        "superseded",
        [],
        {},
    )
    assert run_doc(seeded, done)["state"] == "arrived" and "ended_reason" not in run_doc(seeded, done)
    assert run_doc(seeded, second)["state"] == "en_route" and "ended_reason" not in run_doc(seeded, second)
    assert run_doc(seeded, other)["state"] == "en_route"  # a different plate is untouched
    assert not seeded.collection("reports").stream()  # superseding writes no report card


def test_a_stale_run_is_superseded_too(client: TestClient, seeded: FakeFirestore) -> None:
    first = start(client)
    seeded.collection("runs").document(first).update({"state": "stale"})
    start(client)
    assert run_doc(seeded, first)["ended_reason"] == "superseded"


def test_end_unknown_run_is_404(client: TestClient) -> None:
    assert_envelope(client.post("/runs", json={"action": "end", "run_id": "run-nope"}), 404, "unknown_run")
    assert_envelope(client.post("/runs", json={"action": "end"}), 404, "unknown_run")


def test_end_sets_state_and_writes_the_report(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client)
    r = client.post("/runs", json={"action": "end", "run_id": rid})
    assert r.status_code == 200 and r.json()["state"] == "ended" and r.json()["report"]["run_id"] == rid
    assert run_doc(seeded, rid)["state"] == "ended"
    assert (
        client.post("/runs", json={"action": "end", "run_id": rid}).json()["report"] == r.json()["report"]
    )  # stored once


# ---- triage, log, confirm, route, brief ------------------------------------------------------------------------------


def test_triage_and_log_are_422_offline(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client)
    for path in ("/triage", "/log"):
        body = assert_envelope(
            client.post(path, json={"run_id": rid, "text": "chest pain"}), 422, "extraction_failed"
        )
        assert body["fallback"] == "form"
    assert not seeded.collection("runs").document(rid).collection("log").stream()


def test_triage_and_log_input_checks(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client)
    assert_envelope(client.post("/triage", json={"run_id": "run-nope", "text": "x"}), 404, "unknown_run")
    assert_envelope(client.post("/triage", json={"run_id": rid}), 400, "bad_request")
    assert_envelope(
        client.post("/triage", json={"run_id": rid, "image_b64": "eA==", "mime": "text/plain"}),
        400,
        "bad_request",
    )
    assert_envelope(client.post("/triage", json={"text": "no run id"}), 422, "validation_error")


def test_confirm_sets_tier_and_defers_routing(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client)
    r = client.post(f"/runs/{rid}/confirm", json={"tier": "critical"})
    assert r.status_code == 200
    assert r.json() == {
        "run_id": rid,
        "confirmed_tier": "critical",
        "patient_on_board": True,
        "routing": None,
    }
    run = run_doc(seeded, rid)
    assert run["confirmed_tier"] == "critical" and run["patient_on_board"] is True
    assert run["routing"]["trace"] == [
        {"fallback": "offline_ai"}
    ]  # the background task ran after the response


def test_confirm_errors(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client)
    assert_envelope(client.post(f"/runs/{rid}/confirm", json={"tier": "dire"}), 400, "bad_tier")
    assert_envelope(client.post("/runs/run-nope/confirm", json={"tier": "critical"}), 404, "unknown_run")


def test_confirm_fire_gets_no_routing(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client, plate=FIRE)
    client.post(f"/runs/{rid}/confirm", json={"tier": "fire_with_trapped"})
    assert "routing" not in run_doc(seeded, rid)


def test_route_endpoint(client: TestClient, seeded: FakeFirestore) -> None:
    assert_envelope(client.post("/route", json={"run_id": "run-nope"}), 404, "unknown_run")
    fire = start(client, plate=FIRE)
    assert_envelope(client.post("/route", json={"run_id": fire}), 409, "not_routable")
    amb = start(client)
    client.post(f"/runs/{amb}/confirm", json={"tier": "urgent"})
    r = client.post("/route", json={"run_id": amb})
    assert r.status_code == 200 and r.json()["hospital_id"].startswith("blr_")


def test_brief_404_and_no_entries(client: TestClient, seeded: FakeFirestore) -> None:
    assert_envelope(client.post("/brief", json={"run_id": "run-nope"}), 404, "unknown_run")
    assert_envelope(client.post("/brief", json={"run_id": start(client)}), 422, "no_log_entries")


def test_brief_from_the_log(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client)
    seeded.collection("runs").document(rid).collection("log").document("0").set(
        {"t": datetime.now(UTC), "fields": {}}
    )
    r = client.post("/brief", json={"run_id": rid})
    assert r.status_code == 200 and r.json()["model"] == "offline" and r.json()["disclaimer"]
    assert seeded.collection("briefs").document(rid).get().exists
    assert run_doc(seeded, rid)["brief_fired"] is True


# ---- location, ack, duty ---------------------------------------------------------------------------------------------


def tick(client: TestClient, rid: str, lat: float = 12.9145, lng: float = 77.6361, **kw: object) -> Response:
    return client.post(
        "/location", json={"run_id": rid, "lat": lat, "lng": lng, "speed_mps": 10, "source": "sim", **kw}
    )


def test_location_unknown_and_ended(client: TestClient, seeded: FakeFirestore) -> None:
    assert_envelope(tick(client, "run-nope"), 404, "unknown_run")
    rid = start(client)
    client.post("/runs", json={"action": "end", "run_id": rid})
    assert assert_envelope(tick(client, rid), 403, "run_not_active")["state"] == "ended"


def test_location_unknown_corridor(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client)
    seeded.collection("runs").document(rid).update({"corridor": "atlantis"})
    assert_envelope(tick(client, rid), 400, "unknown_corridor")


def test_first_tick_starts_the_drive(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client, scenario="blr-two-vehicles", source="sim", destination=BLR_HOSPITAL)
    t0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    out = tick(client, rid, t=t0.isoformat()).json()
    assert out["state"] == "en_route" and out["next_junction"] == "blr_j1" and out["traffic"] == "scenario"
    run = run_doc(seeded, rid)
    assert run["first_tick_at"] == t0 and run["next_junction_id"] == "blr_j1"
    tick(client, rid, t=(t0 + timedelta(seconds=10)).isoformat())
    assert run_doc(seeded, rid)["first_tick_at"] == t0  # set once


def test_brief_waits_for_distance_driven(client: TestClient, seeded: FakeFirestore) -> None:
    """ETA is under 300 s from the start, but a brief needs a junction passed or 500 m driven, and never on a scenario's first tick."""
    far = {"name": "H", "lat": 12.9145 + 0.018, "lng": 77.6361}  # about 2 km north
    rid = start(client, scenario="blr-two-vehicles", source="sim", destination=far)
    seeded.collection("runs").document(rid).collection("log").document("0").set(
        {"t": datetime.now(UTC), "fields": {}}
    )
    t0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    out = [
        tick(client, rid, 12.9145 + dlat, t=(t0 + timedelta(seconds=s)).isoformat()).json()
        for dlat, s in ((0, 0), (0.0006, 6))
    ]
    assert [o["brief_due"] for o in out] == [False, False] and not run_doc(seeded, rid)["brief_fired"]
    out.append(
        tick(client, rid, 12.9145 + 0.006, t=(t0 + timedelta(seconds=12)).isoformat()).json()
    )  # 660 m driven
    assert out[-1]["brief_due"] is True  # due in this response; the brief itself is written after it
    assert (
        run_doc(seeded, rid)["brief_fired"] is True and seeded.collection("briefs").document(rid).get().exists
    )


def alerting_run(client: TestClient, db: FakeFirestore) -> tuple[str, int]:
    """A scenario ambulance driven until its first alert exists; returns (run id, alert number)."""
    import json
    from pathlib import Path

    sc = json.loads(
        (Path(main.__file__).resolve().parents[1] / "data/scenarios/blr-two-vehicles.json").read_text()
    )
    rid = start(client, scenario="blr-two-vehicles", source="sim", destination=BLR_HOSPITAL)
    client.post(f"/runs/{rid}/confirm", json={"tier": "critical"})
    base = datetime.now(UTC)
    for k in sc["vehicles"][0]["ticks"]:
        out = tick(
            client,
            rid,
            k["lat"],
            k["lng"],
            speed_mps=k["speed_mps"],
            t=(base + timedelta(seconds=k["t"])).isoformat(),
        ).json()
        if out["alerts_fired"]:
            return rid, 0
    raise AssertionError("the scenario fired no alert")


def test_ack_sets_latency_and_is_idempotent(client: TestClient, seeded: FakeFirestore) -> None:
    rid, n = alerting_run(client, seeded)
    alert = seeded.collection("runs").document(rid).collection("alerts").document(str(n))
    jid = alert.get().to_dict()["junction_id"]
    alert.update({"created_at": datetime.now(UTC) - timedelta(seconds=10)})
    body = {"run_id": rid, "alert_n": n, "junction_id": jid, "device_id": "cop-1"}
    first = client.post("/ack", json=body).json()
    assert (
        first["ok"] is True
        and 10 <= first["ack_latency_s"] < 12
        and first["latency_s"] == first["ack_latency_s"]
    )
    stored = alert.get().to_dict()
    assert stored["acked_by"] == "cop-1" and stored["ack_latency_s"] == first["ack_latency_s"]
    assert client.post("/ack", json={**body, "device_id": "cop-2"}).json() == first  # the first ACK stands
    assert alert.get().to_dict()["acked_by"] == "cop-1"
    assert_envelope(client.post("/ack", json={**body, "junction_id": "blr_j9"}), 404, "unknown_alert")
    assert_envelope(client.post("/ack", json={**body, "alert_n": 99}), 404, "unknown_alert")


def test_unacked_alert_older_than_20s_is_escalated(client: TestClient, seeded: FakeFirestore) -> None:
    rid, n = alerting_run(client, seeded)
    alerts = seeded.collection("runs").document(rid).collection("alerts")
    assert alerts.document(str(n)).get().to_dict()["escalated"] is False
    alerts.document(str(n)).update({"created_at": datetime.now(UTC) - timedelta(seconds=25)})
    tick(client, rid, t=(datetime.now(UTC) + timedelta(seconds=600)).isoformat())
    a = alerts.document(str(n)).get().to_dict()
    assert a["escalated"] is True and a["escalated_at"] is not None
    escalations = [
        d.to_dict() for d in seeded.collection("audit").stream() if d.to_dict()["action"] == "escalation"
    ]
    assert [(e["run_id"], e["alert_n"]) for e in escalations] == [(rid, n)]
    tick(client, rid, t=(datetime.now(UTC) + timedelta(seconds=700)).isoformat())  # flagged once only
    assert len([d for d in seeded.collection("audit").stream() if d.to_dict()["action"] == "escalation"]) == 1


def test_acked_alert_is_never_escalated(client: TestClient, seeded: FakeFirestore) -> None:
    rid, n = alerting_run(client, seeded)
    alert = seeded.collection("runs").document(rid).collection("alerts").document(str(n))
    jid = alert.get().to_dict()["junction_id"]
    client.post("/ack", json={"run_id": rid, "alert_n": n, "junction_id": jid})
    alert.update({"created_at": datetime.now(UTC) - timedelta(seconds=60)})
    tick(client, rid, t=(datetime.now(UTC) + timedelta(seconds=600)).isoformat())
    assert alert.get().to_dict()["escalated"] is False


def test_duty_writes_both_junction_id_forms(client: TestClient, seeded: FakeFirestore) -> None:
    for jid in ("j3", "blr_j3"):
        r = client.post(
            "/duty",
            json={"corridor": "blr", "junction_id": jid, "device_id": "d1", "on": True, "name": "Ravi"},
        )
        assert r.status_code == 200 and r.json()["on"] is True
        doc = seeded.collection("duty").document("blr_j3").get().to_dict()
        assert (doc["device_id"], doc["name"], doc["on"]) == ("d1", "Ravi", True)
    client.post("/duty", json={"corridor": "blr", "junction_id": "j3", "device_id": "d1", "on": False})
    assert seeded.collection("duty").document("blr_j3").get().to_dict()["on"] is False


def test_duty_errors(client: TestClient) -> None:
    base = {"device_id": "d1", "on": True}
    assert_envelope(
        client.post("/duty", json={**base, "corridor": "mars", "junction_id": "j1"}), 400, "unknown_corridor"
    )
    assert_envelope(
        client.post("/duty", json={**base, "corridor": "blr", "junction_id": "j99"}), 404, "unknown_junction"
    )


# ---- grounded rationale, housekeeping, alert guard ------------------------------------------------------------------


def run_with_alert(
    db: FakeFirestore, rid: str, tick_age_s: int, alert_age_s: int, acked: bool = False
) -> None:
    now = datetime.now(UTC)
    db.collection("runs").document(rid).set(
        {"state": "en_route", "last_tick_at": now - timedelta(seconds=tick_age_s), "ahead_ids": ["blr_j3"]}
    )
    db.collection("runs").document(rid).collection("alerts").document("0").set(
        {
            "junction_id": "blr_j3",
            "stage": "PREPARE",
            "acked_at": now if acked else None,
            "escalated": False,
            "created_at": now - timedelta(seconds=alert_age_s),
        }
    )


def test_rationale_keeps_a_grounded_sentence_and_replaces_an_invented_one(
    seeded: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    seq = priority.sequence(
        [
            {
                "run_id": "f",
                "vehicle_type": "fire",
                "tier": "fire_with_trapped",
                "eta_s": 90,
                "approach": "S",
            },
            {"run_id": "a", "vehicle_type": "ambulance", "tier": "critical", "eta_s": 30, "approach": "E"},
        ]
    )
    monkeypatch.setattr(main, "offline", lambda: False)
    monkeypatch.setattr(main, "translate", lambda text, lang: f"[{lang}] {text}")
    seen: list = []
    reply = {"text": "The fire engine goes first because its tier is higher."}

    def explain(facts: list, lang: str) -> str:
        seen.append(facts)
        return reply["text"]

    monkeypatch.setattr(main.gemini, "explain_sequence", explain)
    junction = seeded.collection("junctions").document("blr_j3")
    junction.update({"phase": {"approach": "S"}})
    main.rationale("blr_j3", seq, "kn")
    assert junction.get().to_dict()["phase"]["rationale"] == reply["text"]
    assert (
        seen[0][0]["reason_code"] == "higher_tier" and seen[0][0]["offset_s_is_gap_assigned_by_rules"] is True
    )
    reply["text"] = "The fire engine goes first because it arrives 12 seconds earlier."  # a false reason
    main.rationale("blr_j3", seq, "kn")
    phase = junction.get().to_dict()["phase"]
    assert phase["rationale"] == (
        "Fire engine with trapped persons goes first: higher priority tier. Ambulance follows 12 s later."
    )
    assert phase["rationale_local"] == "[kn] " + phase["rationale"]


def test_housekeeping_is_off_without_a_token_and_checks_it_otherwise(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HOUSEKEEPING_TOKEN", raising=False)
    assert_envelope(client.post("/housekeeping", headers={"X-Housekeeping-Token": "x"}), 404, "not_found")
    monkeypatch.setenv("HOUSEKEEPING_TOKEN", "s3cret")
    assert_envelope(client.post("/housekeeping"), 403, "forbidden")
    assert_envelope(client.post("/housekeeping", headers={"X-Housekeeping-Token": "nope"}), 403, "forbidden")
    ok = client.post("/housekeeping", headers={"X-Housekeeping-Token": "s3cret"})
    assert ok.status_code == 200 and ok.json() == {"stale": 0, "escalated": 0, "runs_checked": 0}


def test_housekeeping_marks_stale_and_escalates_without_a_tick(
    client: TestClient, db: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOUSEKEEPING_TOKEN", "s3cret")
    run_with_alert(db, "quiet", tick_age_s=60, alert_age_s=40)  # no tick for a minute, alert unanswered
    run_with_alert(db, "fresh", tick_age_s=2, alert_age_s=5)  # ticking, alert young
    run_with_alert(db, "acked", tick_age_s=2, alert_age_s=40, acked=True)
    out = client.post("/housekeeping", headers={"X-Housekeeping-Token": "s3cret"}).json()
    assert out == {"stale": 1, "escalated": 1, "runs_checked": 3}
    assert run_doc(db, "quiet")["state"] == "stale" and run_doc(db, "fresh")["state"] == "en_route"
    alert = db.collection("runs").document("quiet").collection("alerts").document("0").get().to_dict()
    assert alert["escalated"] is True
    assert [d.to_dict()["run_id"] for d in db.collection("audit").stream()] == ["quiet"]
    again = client.post("/housekeeping", headers={"X-Housekeeping-Token": "s3cret"}).json()
    assert again["stale"] == 0 and again["escalated"] == 0  # each fires once only


def test_claim_alert_fires_each_stage_once(db: FakeFirestore) -> None:
    ref = db.collection("runs").document("r1")
    ref.set({"state": "en_route"})
    assert main.claim_alert(ref, "blr_j3", "PREPARE", "PREPARE", 120) == 0
    assert (
        main.claim_alert(ref, "blr_j3", "PREPARE", "PREPARE", 120) is None
    )  # a second tick with the same stale view
    assert main.claim_alert(ref, "blr_j3", "PREPARE", "UPDATE", 150) is None  # grew only 30 m
    assert main.claim_alert(ref, "blr_j3", "PREPARE", "UPDATE", 300) == 1
    assert main.claim_alert(ref, "blr_j3", "STOP", "STOP", 300) == 2
    assert main.claim_alert(ref, "blr_j3", "STOP", "STOP", 300) is None
    assert main.claim_alert(ref, "blr_j4", "STOP", "STOP", 0) == 3  # another junction has its own state
    doc = run_doc(db, "r1")
    assert doc["alert_count"] == 4 and doc["alert_state"]["blr_j3"] == {
        "prepare": True,
        "stop": True,
        "jam_m": 300,
    }
