"""After-action report: the deterministic timeline builder and POST /runs/{id}/after-action (offline, fake Firestore)."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

import aar
from fakefs import FakeFirestore
from test_api import assert_envelope, start

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


def at(s: int) -> datetime:
    return T0 + timedelta(seconds=s)


def test_timeline_is_built_in_time_order_from_the_record() -> None:
    run = {
        "vehicle_type": "ambulance",
        "vehicle_plate": "KA01AB1234",
        "state": "arrived",
        "started_at": at(0),
        "first_tick_at": at(30),
    }
    alerts = [
        {
            "junction_id": "blr_j3",
            "stage": "STOP",
            "created_at": at(200),
            "acked_at": at(206),
            "ack_latency_s": 6.0,
        },
        {
            "junction_id": "blr_j3",
            "stage": "PREPARE",
            "jam_m": 400,
            "created_at": at(100),
            "escalated_at": at(121),
        },
    ]
    report = {"ended_at": at(300).isoformat()}  # a stored report may carry ISO strings
    tl = aar.timeline(run, [{"t": at(60), "kind": "voice"}, {"kind": "form"}], alerts, report)
    assert [e["t"] for e in tl] == [at(s).isoformat() for s in (0, 30, 60, 100, 121, 200, 206, 300)]
    assert [e["event"] for e in tl] == [
        "Run created (ambulance KA01AB1234)",
        "First location tick, drive started",
        "Crew log entry (voice)",
        "PREPARE alert at blr_j3, 400 m queue",
        "Alert at blr_j3 escalated with no acknowledgement",
        "STOP alert at blr_j3",
        "Alert at blr_j3 acknowledged after 6.0 s",
        "Run arrived",
    ]  # the log entry with no time is dropped


def test_timeline_ends_at_the_last_tick_without_a_report() -> None:
    run = {"state": "ended", "ticks": [{"t": at(10)}, {"t": at(50)}]}
    assert aar.timeline(run, [], [], None) == [{"t": at(50).isoformat(), "event": "Run ended"}]


def finished(client: TestClient, db: FakeFirestore, state: str = "ended") -> str:
    rid = start(client)
    db.collection("runs").document(rid).update({"state": state})
    return rid


def test_after_action_404_and_409(client: TestClient, seeded: FakeFirestore) -> None:
    assert_envelope(client.post("/runs/run-nope/after-action"), 404, "unknown_run")
    assert_envelope(client.post(f"/runs/{start(client)}/after-action"), 409, "run_not_finished")


def test_after_action_offline_stub_is_stored(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client)
    client.post("/runs", json={"action": "end", "run_id": rid})  # writes the report card
    r = client.post(f"/runs/{rid}/after-action")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "offline" and body["disclaimer"] and body["generated_at"]
    assert body["summary"] and body["issues"] and body["recommendations"]
    assert [e["event"] for e in body["timeline"]][-1] == "Run ended"
    assert seeded.collection("after_action").document(rid).get().exists


def test_after_action_is_idempotent_until_regenerated(client: TestClient, seeded: FakeFirestore) -> None:
    rid = finished(client, seeded)
    first = client.post(f"/runs/{rid}/after-action").json()
    seeded.collection("after_action").document(rid).update({"summary": "edited"})
    assert (
        client.post(f"/runs/{rid}/after-action").json()["summary"] == "edited"
    )  # stored doc, no regeneration
    again = client.post(f"/runs/{rid}/after-action?regenerate=1").json()
    assert again["summary"] == first["summary"] and again["generated_at"] >= first["generated_at"]
    assert seeded.collection("after_action").document(rid).get().to_dict()["summary"] == first["summary"]
