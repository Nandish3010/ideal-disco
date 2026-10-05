"""Report card at run end: simulated with-vs-without baseline, written to Firestore reports/{run_id} and BigQuery corridor.run_reports."""

import os
from datetime import UTC, datetime

from corridor import CORRIDORS
from logctx import log

PROJECT = os.environ.get("GCP_PROJECT", "green-corridor-2026")
TABLE = f"{PROJECT}.corridor.run_reports"
# (name, BigQuery type, mode); the report dict maps 1:1
SCHEMA = [
    ("corridor", "STRING"),
    ("run_id", "STRING"),
    ("vehicle_type", "STRING"),
    ("confirmed_tier", "STRING"),
    ("started_at", "TIMESTAMP"),
    ("ended_at", "TIMESTAMP"),
    ("actual_s", "FLOAT"),
    ("baseline_s", "FLOAT"),
    ("minutes_saved", "FLOAT"),
    ("junctions_cleared", "INTEGER"),
    ("alerts", "INTEGER"),
    ("ack_latency_s", "FLOAT", "REPEATED"),
    ("avg_ack_latency_s", "FLOAT"),
    ("escalations", "INTEGER"),
    ("distance_m", "FLOAT"),
    ("method", "STRING"),
]
DRAIN_MPS = 2.0  # queue drain rate, same constant as leadtime.clear_seconds
_table_ready = False


def compute(run_id, run, alerts, audits, ended_at):
    """alerts: alert dicts; audits: audit dicts for this run. Baseline per junction cleared: remaining red (arrival at
    mid-red = cycle_s / 4) plus the queue drain time jam_m / 2.0, jam_m from that junction's PREPARE alert (0 if none)."""
    started = (
        run.get("first_tick_at") or run["started_at"]
    )  # the drive starts at the first tick, not at run creation
    actual_s = max((ended_at - started).total_seconds(), 0)
    cleared = {a["junction_id"] for a in audits if a.get("action") == "preempt_requested"}
    cycles = {f"{run['corridor']}_{j['id']}": j["cycle_s"] for j in CORRIDORS[run["corridor"]]["junctions"]}
    # PREPARE's jam_m wins; a junction with only a STOP alert uses that one
    jam = {
        a["junction_id"]: a.get("jam_m", 0)
        for a in sorted(alerts, key=lambda a: a["stage"] == "PREPARE")
        if a["stage"] != "UPDATE"
    }
    stops = sum(cycles.get(j, 0) / 4 + jam.get(j, 0) / DRAIN_MPS for j in cleared)
    acks = [a["ack_latency_s"] for a in alerts if a.get("ack_latency_s") is not None]
    return {
        "corridor": run["corridor"],
        "run_id": run_id,
        "vehicle_type": run["vehicle_type"],
        "confirmed_tier": run.get("confirmed_tier"),
        "started_at": started,
        "ended_at": ended_at,
        "actual_s": round(actual_s),
        "baseline_s": round(actual_s + stops),
        "minutes_saved": round(stops / 60, 1),
        "junctions_cleared": len(cleared),
        "alerts": len(alerts),
        "ack_latency_s": acks,
        "avg_ack_latency_s": round(sum(acks) / len(acks), 1) if acks else None,
        "escalations": sum(a.get("action") == "escalation" for a in audits),
        "distance_m": run.get("distance_m", 0),
        "method": "simulated-baseline",
    }


def to_bigquery(doc):  # pragma: no cover - network
    """Insert the row; failure logs report_bq_error and never raises."""
    global _table_ready
    try:
        from google.cloud import bigquery

        bq = bigquery.Client(project=PROJECT)
        if not _table_ready:
            bq.create_table(
                bigquery.Table(
                    TABLE,
                    schema=[bigquery.SchemaField(n, t, m[0] if m else "NULLABLE") for n, t, *m in SCHEMA],
                ),
                exists_ok=True,
            )
            _table_ready = True
        row = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in doc.items()}
        errs = bq.insert_rows_json(TABLE, [row])
        if errs:
            raise RuntimeError(str(errs)[:200])
    except (
        Exception
    ) as e:  # ponytail: any failure, BigQuery is the analytics copy and Firestore stays the record
        log(event="report_bq_error", run_id=doc["run_id"], error=type(e).__name__, detail=str(e)[:200])


def write(run_id, run_ref):
    """Compute and store the report once per run (a later call returns the stored one). Reads the run fresh, so call it after the
    run's last update. ended_at is the last GPS tick (arrival), else now."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    from firestore_client import db

    existing = db.collection("reports").document(run_id).get()
    if existing.exists:
        return _jsonable(existing.to_dict())
    run = run_ref.get().to_dict()
    if run.get("corridor") not in CORRIDORS:
        return None
    ticks = run.get("ticks") or []
    alerts = [d.to_dict() for d in run_ref.collection("alerts").stream()]
    audits = [
        d.to_dict() for d in db.collection("audit").where(filter=FieldFilter("run_id", "==", run_id)).stream()
    ]
    doc = compute(run_id, run, alerts, audits, ticks[-1]["t"] if ticks else datetime.now(UTC))
    db.collection("reports").document(run_id).set(doc)
    to_bigquery(doc)
    log(
        event="report_written",
        run_id=run_id,
        minutes_saved=doc["minutes_saved"],
        junctions_cleared=doc["junctions_cleared"],
    )
    return _jsonable(doc)


def _jsonable(doc):
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in doc.items()}


if __name__ == "__main__":
    t0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    run = {
        "corridor": "blr",
        "vehicle_type": "ambulance",
        "confirmed_tier": "critical",
        "started_at": t0,
        "distance_m": 5200,
    }
    t1 = datetime(2026, 10, 5, 9, 9, tzinfo=UTC)
    alerts = [
        {"junction_id": "blr_j3", "stage": "STOP", "jam_m": 100, "ack_latency_s": 4.0},
        {"junction_id": "blr_j3", "stage": "PREPARE", "jam_m": 400, "ack_latency_s": 8.0},
        {"junction_id": "blr_j4", "stage": "STOP", "jam_m": 0, "ack_latency_s": None},
    ]
    audits = [
        {"action": "preempt_requested", "junction_id": "blr_j3"},
        {"action": "preempt_requested", "junction_id": "blr_j3"},
        {"action": "preempt_requested", "junction_id": "blr_j4"},
        {"action": "escalation", "junction_id": "blr_j4"},
    ]
    r = compute("run-x", run, alerts, audits, t1)
    c3, c4 = (next(j["cycle_s"] for j in CORRIDORS["blr"]["junctions"] if j["id"] == i) for i in ("j3", "j4"))
    stops = c3 / 4 + 400 / 2 + c4 / 4  # j3 uses its PREPARE jam (400), j4 has only a STOP alert with jam 0
    assert (
        r["actual_s"] == 540
        and r["baseline_s"] == round(540 + stops)
        and r["minutes_saved"] == round(stops / 60, 1)
    ), r
    assert (
        r["junctions_cleared"],
        r["alerts"],
        r["escalations"],
        r["ack_latency_s"],
        r["avg_ack_latency_s"],
    ) == (2, 3, 1, [4.0, 8.0], 6.0)
    first = datetime(2026, 10, 5, 9, 4, tzinfo=UTC)  # run created at 9:00, first tick at 9:04: 5 min drive
    r2 = compute("r", {**run, "first_tick_at": first}, [], [], t1)
    assert r2["actual_s"] == 300 and r2["started_at"] == first
    assert (
        compute("r", run, [], [], t1)["baseline_s"] == 540
        and compute("r", run, [], [], t1)["avg_ack_latency_s"] is None
    )
    assert [f[0] for f in SCHEMA] == list(r)  # BigQuery schema covers exactly the report keys, in order
    print("report ok")
