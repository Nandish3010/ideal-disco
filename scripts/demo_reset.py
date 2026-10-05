"""Reset the demo Firestore to a clean slate between rehearsals. Dry run by default (prints counts); --apply writes.
Needs GOOGLE_APPLICATION_CREDENTIALS. Run from the repo root: python3 scripts/demo_reset.py [--apply]
Ends every run not already ended/arrived; deletes runs/*/alerts, audit/*, reports/*, briefs/*, duty/*;
closes all incidents and deletes those already closed for over 1 h (except the seed INC-0001); clears junctions/*.phase; nulls vehicles/*.bound_device_id.
Keeps vehicles, junctions and incidents docs, and the runs themselves (so ended runs stay readable)."""

import os
import sys
from datetime import datetime, timedelta, timezone

from google.cloud import firestore

APPLY = "--apply" in sys.argv
db = firestore.Client(project=os.environ.get("GCP_PROJECT", "green-corridor-2026"))
ops = []  # (label, doc ref, None to delete | dict to update)


def plan(label, refs, change=None):
    refs = list(refs)
    ops.extend((label, r, change) for r in refs)
    return len(refs)


runs = list(db.collection("runs").stream())
plan(
    "runs ended",
    [r.reference for r in runs if r.to_dict().get("state") not in ("ended", "arrived")],
    {"state": "ended"},
)
plan("alerts deleted", [a.reference for r in runs for a in r.reference.collection("alerts").stream()])
for col in ("audit", "reports", "briefs", "duty"):
    plan(f"{col} deleted", [d.reference for d in db.collection(col).stream()])
old = datetime.now(timezone.utc) - timedelta(hours=1)
plan(
    "old closed incidents deleted",
    [
        i.reference
        for i in db.collection("incidents").stream()
        if i.id != "INC-0001"
        and i.to_dict().get("state") == "closed"
        and (i.to_dict().get("created_at") or old) < old
    ],
)
plan(
    "incidents closed",
    [i.reference for i in db.collection("incidents").stream() if i.to_dict().get("state") != "closed"],
    {"state": "closed"},
)
plan(
    "junction phases cleared",
    [j.reference for j in db.collection("junctions").stream() if j.to_dict().get("phase") is not None],
    {"phase": None},
)
plan(
    "vehicles unbound",
    [
        v.reference
        for v in db.collection("vehicles").stream()
        if v.to_dict().get("bound_device_id") is not None
    ],
    {"bound_device_id": None},
)

counts = {}
for label, _, _ in ops:
    counts[label] = counts.get(label, 0) + 1
for label in (
    "runs ended",
    "alerts deleted",
    "audit deleted",
    "reports deleted",
    "briefs deleted",
    "duty deleted",
    "old closed incidents deleted",
    "incidents closed",
    "junction phases cleared",
    "vehicles unbound",
):
    print(f"{label}: {counts.get(label, 0)}")

if APPLY:
    for i in range(0, len(ops), 400):
        batch = db.batch()
        for _, ref, change in ops[i : i + 400]:
            batch.delete(ref) if change is None else batch.update(ref, change)
        batch.commit()
    print("applied")
else:
    print("dry run, nothing written; pass --apply")
