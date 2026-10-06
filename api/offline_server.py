"""The API on an in-memory Firestore with the three scenario vehicles seeded: no credentials, no Google calls. For the
contract run (`make contract`) and the load test (`make loadtest`), which talk to it over HTTP:
    cd api && RATE_LIMIT_DISABLED=1 uvicorn offline_server:app --port 8081
Not for production; the image never imports it."""

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import httpx

# the offline switches must be set before main is imported
for name, value in {"OFFLINE_AI": "1", "DEVICE_TOKENS_DISABLED": "1", "GEMINI_MODEL": "offline"}.items():
    os.environ.setdefault(name, value)
sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))

from fakefs import FakeFirestore, seed  # noqa: E402


def offline_routes(*_: object, **__: object) -> None:
    raise httpx.ConnectError(
        "offline"
    )  # the Routes call fails like an outage: traffic reads as NORMAL, stale


httpx.post = offline_routes  # type: ignore[assignment]  # routes_api calls httpx.post; no Routes call, no network

fake = FakeFirestore()
seed(fake)
# the documentation examples name these, so the examples phase of the contract run reaches real documents
now = datetime.now(UTC)
fake.collection("incidents").document("INC-4BC6E7").set(
    {"type": "cardiac", "severity_note": "Synthetic demo incident", "created_at": now, "state": "open"}
)
fake.collection("runs").document("run-amb-1").set(
    {
        "vehicle_plate": "KA01AB1234",
        "vehicle_type": "ambulance",
        "incident_id": "INC-4BC6E7",
        "corridor": "blr",
        "source": "sim",
        "state": "en_route",
        "patient_on_board": False,
        "brief_fired": False,
        "started_at": now,
        "scenario": "blr-two-vehicles",
    }
)
fake.collection("runs").document("run-amb-1").collection("log").document("1").set(
    {"t": now, "kind": "form", "transcript_en": "chest pain", "fields": {"complaint": "chest pain"}}
)
fake.collection("runs").document("run-amb-1").collection("alerts").document("0").set(
    {"junction_id": "blr_j3", "stage": "PREPARE", "created_at": now, "acked_at": None, "escalated": False}
)
stub = ModuleType("firestore_client")  # the real one builds a credentialed client at import
stub.db = fake  # type: ignore[attr-defined]
sys.modules["firestore_client"] = stub

import report  # noqa: E402
from main import app  # noqa: E402, F401

report.to_bigquery = lambda doc: None  # the analytics copy of a report card is a BigQuery insert: not offline
