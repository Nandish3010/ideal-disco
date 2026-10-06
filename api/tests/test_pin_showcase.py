"""scripts/pin_showcase.py: which run settings/showcase pins, against the in-memory Firestore."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fakefs import FakeFirestore

spec = importlib.util.spec_from_file_location(
    "pin_showcase", Path(__file__).resolve().parents[2] / "scripts" / "pin_showcase.py"
)
assert spec and spec.loader
pin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pin)

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
TRACE = [{"text": f"step {i}"} for i in range(4)]


def run(
    db: FakeFirestore,
    rid: str,
    age_min: int,
    *,
    state: str = "arrived",
    vtype: str = "ambulance",
    trace: list | None = None,
    brief: bool = True,
    alerts: list[dict[str, Any]] | None = None,
) -> None:
    doc = {
        "state": state,
        "vehicle_type": vtype,
        "vehicle_plate": "KA01AB1234",
        "started_at": NOW - timedelta(minutes=age_min),
        "routing": {"trace": TRACE if trace is None else trace},
    }
    db.collection("runs").document(rid).set(doc)
    if brief:
        db.collection("briefs").document(rid).set({"model": "gemini-3-flash-preview"})
    for n, a in enumerate(alerts if alerts is not None else [{"stage": "PREPARE", "acked_at": NOW}]):
        db.collection("runs").document(rid).collection("alerts").document(str(n)).set(a)


def test_pins_the_newest_qualifying_run(db: FakeFirestore) -> None:
    run(db, "old", 90)
    run(db, "new", 10)
    doc = pin.choose(db, "2026-10-06")
    assert doc["run_id"] == "new" and doc["brief_run_id"] == "new"
    assert doc["alert_path"] == "runs/new/alerts/0"
    assert "4 routing steps" in doc["note"] and "2026-10-06" in doc["note"]


def test_skips_runs_that_miss_any_requirement(db: FakeFirestore) -> None:
    run(db, "good", 90)
    run(db, "en-route", 1, state="en_route")
    run(db, "fire", 2, vtype="fire")
    run(db, "short-trace", 3, trace=TRACE[:3])
    run(db, "no-brief", 4, brief=False)
    run(db, "no-ack", 5, alerts=[{"stage": "PREPARE"}])
    run(db, "no-alerts", 6, alerts=[])
    assert pin.choose(db)["run_id"] == "good"


def test_nothing_qualifies(db: FakeFirestore) -> None:
    run(db, "r", 5, brief=False)
    assert pin.choose(db) is None


def test_alert_is_the_prepare_with_speech_and_the_longest_queue(db: FakeFirestore) -> None:
    acked = {"acked_at": NOW}
    run(
        db,
        "r",
        5,
        alerts=[
            {"stage": "STOP", "audio_url": "u", **acked},
            {"stage": "PREPARE", "audio_url": "u", "jam_m": 120, **acked},
            {"stage": "PREPARE", "audio_url": "u", "jam_m": 520, **acked},
            {"stage": "PREPARE", "audio_url": None, "jam_m": 900, **acked},
            {"stage": "PREPARE", "audio_url": "u", "jam_m": 900},  # not acked
        ],
    )
    assert pin.choose(db)["alert_path"] == "runs/r/alerts/2"
    run(db, "s", 1, alerts=[{"stage": "STOP", **acked}, {"stage": "STOP", "audio_url": "u", **acked}])
    assert pin.choose(db)["alert_path"] == "runs/s/alerts/1"
