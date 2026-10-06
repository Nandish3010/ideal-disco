"""Pin the run the read-only judge panels show: writes settings/showcase {run_id, alert_path, brief_run_id, note}.
Picks, from live Firestore, the most recent arrived ambulance run that has a brief, a routing trace of at least 4 steps
and at least one acked alert. /cop "Sample alert", /hospital "Last handover", /vehicle "Last routing decision" and /story
prefer the pin and fall back to the newest suitable data when it is missing or stale.
Dry run by default (prints the doc); --apply writes it. Needs GOOGLE_APPLICATION_CREDENTIALS. From the repo root:
python3 scripts/pin_showcase.py [--apply]"""

import os
import sys
from datetime import UTC, datetime
from typing import Any

MIN_TRACE = 4
EPOCH = datetime.min.replace(tzinfo=UTC)


def best_alert(alerts: list[Any]) -> Any:
    """The acked alert to play: PREPARE with speech and the longest queue, else any acked one with speech, else the first."""
    acked = sorted((a for a in alerts if a.to_dict().get("acked_at")), key=lambda a: a.id)
    prepare = [a for a in acked if a.to_dict().get("stage") == "PREPARE" and a.to_dict().get("audio_url")]
    spoken = [a for a in acked if a.to_dict().get("audio_url")]
    return max(prepare, key=lambda a: a.to_dict().get("jam_m") or 0, default=None) or (spoken or acked)[0]


def choose(db: Any, today: str = "") -> dict | None:
    """The settings/showcase doc for the newest run that qualifies, else None."""
    arrived = list(db.collection("runs").where("state", "==", "arrived").stream())
    for r in sorted(arrived, key=lambda r: (r.to_dict() or {}).get("started_at") or EPOCH, reverse=True):
        d = r.to_dict() or {}
        steps = len((d.get("routing") or {}).get("trace") or [])
        alerts = list(r.reference.collection("alerts").stream())
        if (
            d.get("vehicle_type") != "ambulance"
            or steps < MIN_TRACE
            or not db.collection("briefs").document(r.id).get().exists
            or not any(a.to_dict().get("acked_at") for a in alerts)
        ):
            continue
        a = best_alert(alerts)
        acked = sum(1 for x in alerts if x.to_dict().get("acked_at"))
        return {
            "run_id": r.id,
            "alert_path": f"runs/{r.id}/alerts/{a.id}",
            "brief_run_id": r.id,
            "note": f"{d.get('vehicle_plate', r.id)}: {steps} routing steps, {acked} acked alerts, brief written. Pinned {today}.",
        }
    return None


def main() -> None:
    from google.cloud import firestore

    db = firestore.Client(project=os.environ.get("GCP_PROJECT", "green-corridor-2026"))
    doc = choose(db, datetime.now(UTC).strftime("%Y-%m-%d"))
    if not doc:
        sys.exit("no arrived ambulance run with a brief, a routing trace of 4+ steps and an acked alert")
    print(doc)
    if "--apply" in sys.argv:
        db.collection("settings").document("showcase").set(doc)
        print("applied")
    else:
        print("dry run, nothing written; pass --apply")


if __name__ == "__main__":
    main()
