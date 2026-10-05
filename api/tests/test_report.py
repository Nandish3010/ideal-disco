from datetime import UTC, datetime

import pytest

import report
from corridor import CORRIDORS
from fakefs import FakeFirestore

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 5, 9, 9, tzinfo=UTC)
RUN = {
    "corridor": "blr",
    "vehicle_type": "ambulance",
    "confirmed_tier": "critical",
    "started_at": T0,
    "distance_m": 5200,
}
CYCLE = {j["id"]: j["cycle_s"] for j in CORRIDORS["blr"]["junctions"]}
ALERTS = [
    {"junction_id": "blr_j3", "stage": "STOP", "jam_m": 100, "ack_latency_s": 4.0},
    {"junction_id": "blr_j3", "stage": "PREPARE", "jam_m": 400, "ack_latency_s": 8.0},
    {"junction_id": "blr_j4", "stage": "STOP", "jam_m": 0, "ack_latency_s": None},
]
AUDITS = [
    {"action": "preempt_requested", "junction_id": "blr_j3"},
    {"action": "preempt_requested", "junction_id": "blr_j3"},  # repeated requests count the junction once
    {"action": "preempt_requested", "junction_id": "blr_j4"},
    {"action": "escalation", "junction_id": "blr_j4"},
]


def test_baseline_maths() -> None:
    r = report.compute("run-x", RUN, ALERTS, AUDITS, T1)
    saved = (
        CYCLE["j3"] / 4 + 400 / 2 + CYCLE["j4"] / 4
    )  # j3 uses its PREPARE jam; j4 only has a STOP alert with jam 0
    assert r["actual_s"] == 540
    assert r["baseline_s"] == round(540 + saved)
    assert r["minutes_saved"] == round(saved / 60, 1)
    assert (r["junctions_cleared"], r["alerts"], r["escalations"]) == (2, 3, 1)
    assert r["ack_latency_s"] == [4.0, 8.0] and r["avg_ack_latency_s"] == 6.0


def test_no_preemption_means_no_saving() -> None:
    r = report.compute("r", RUN, [], [], T1)
    assert r["baseline_s"] == r["actual_s"] == 540
    assert r["minutes_saved"] == 0 and r["avg_ack_latency_s"] is None


def test_update_alerts_do_not_set_the_queue() -> None:
    alerts = [{"junction_id": "blr_j3", "stage": "UPDATE", "jam_m": 900}]
    r = report.compute("r", RUN, alerts, [{"action": "preempt_requested", "junction_id": "blr_j3"}], T1)
    assert r["baseline_s"] - r["actual_s"] == round(CYCLE["j3"] / 4)


def test_drive_starts_at_the_first_tick() -> None:
    first = datetime(2026, 10, 5, 9, 4, tzinfo=UTC)
    r = report.compute("r", {**RUN, "first_tick_at": first}, [], [], T1)
    assert r["actual_s"] == 300 and r["started_at"] == first


def test_never_negative() -> None:
    assert report.compute("r", RUN, [], [], T0.replace(minute=-0))["actual_s"] == 0


def test_schema_matches_report_keys() -> None:
    assert [f[0] for f in report.SCHEMA] == list(report.compute("r", RUN, [], [], T1))


@pytest.fixture
def no_bq(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    rows: list[dict] = []
    monkeypatch.setattr(report, "to_bigquery", rows.append)
    return rows


def test_write_is_stored_once(db: FakeFirestore, no_bq: list[dict]) -> None:
    ref = db.collection("runs").document("run-1")
    ref.set({**RUN, "ticks": [{"t": T1}], "first_tick_at": T0})
    db.collection("audit").add({"run_id": "run-1", "action": "preempt_requested", "junction_id": "blr_j3"})
    first = report.write("run-1", ref)
    assert first["actual_s"] == 540 and first["junctions_cleared"] == 1
    assert isinstance(first["started_at"], str)  # ISO strings out
    assert db.collection("reports").document("run-1").get().exists
    ref.update({"first_tick_at": T1})  # a later call returns the stored report, no recompute
    assert report.write("run-1", ref)["actual_s"] == 540
    assert len(no_bq) == 1


def test_write_skips_unknown_corridor(db: FakeFirestore, no_bq: list[dict]) -> None:
    ref = db.collection("runs").document("run-2")
    ref.set({**RUN, "corridor": "nowhere"})
    assert report.write("run-2", ref) is None and not no_bq
