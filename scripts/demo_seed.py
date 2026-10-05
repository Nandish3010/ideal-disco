"""Seed the (default) Firestore database: vehicles, junctions (both corridors), one incident.
Run from repo root with GOOGLE_APPLICATION_CREDENTIALS set: python3 scripts/demo_seed.py"""
import json, os
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import firestore

db = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT", "green-corridor-2026"))

for plate, vtype, agency in [("KA01AB1234", "ambulance", "108 Karnataka"),
                             ("KA01FE5678", "fire", "Karnataka Fire & Emergency"),
                             ("KA01PC9012", "police", "Bengaluru City Police")]:
    db.collection("vehicles").document(plate).set({"type": vtype, "agency": agency, "active": True})

for f in sorted(Path("data/corridors").glob("*.json")):
    c = json.loads(f.read_text())
    for j in c["junctions"]:
        db.collection("junctions").document(f"{c['id']}_{j['id']}").set({"phase": None, "lang": c["lang"]})

db.collection("incidents").document("INC-0001").set({
    "type": "cardiac", "severity_note": "Synthetic demo incident: chest pain, adult male",
    "created_at": datetime.now(timezone.utc), "state": "active"})
print("seeded")
