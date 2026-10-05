import base64
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.api_core.exceptions import GoogleAPIError
from pydantic import BaseModel

import acuity
from firestore_client import db
from gemini import ExtractionFailed, extract, log

app = FastAPI(title="corridor-api")
# ponytail: demo, no auth, any origin
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

TIERS = {"critical", "urgent", "stable", "fire", "fire_with_trapped", "police", "police_with_incident"}


def todo(name: str) -> JSONResponse:
    return JSONResponse({"todo": name}, status_code=501)


def err(status: int, code: str, **kw) -> JSONResponse:
    return JSONResponse({"error": code, **kw}, status_code=status)


@app.exception_handler(GoogleAPIError)
def firestore_down(request, exc):
    log(event="firestore_error", path=request.url.path, error=type(exc).__name__, detail=str(exc)[:200])
    return err(503, "store_unavailable")


class Bind(BaseModel):
    plate: str
    device_id: str


class Incident(BaseModel):
    type: str
    severity_note: str = ""


class RunReq(BaseModel):
    action: str  # start | end
    plate: Optional[str] = None
    incident_id: Optional[str] = None
    corridor: Optional[str] = None
    destination: Optional[dict] = None
    source: str = "gps"
    run_id: Optional[str] = None


class Triage(BaseModel):
    run_id: str
    vehicle_type: Optional[str] = None
    text: Optional[str] = None
    audio_b64: Optional[str] = None
    mime: Optional[str] = None
    lang_hint: Optional[str] = None
    kind: Optional[str] = None  # /log only


class Confirm(BaseModel):
    tier: str


@app.get("/health")
def health():
    return {"ok": True, "model": os.environ.get("GEMINI_MODEL")}


@app.post("/vehicles/bind")
def vehicles_bind(b: Bind):
    ref = db.collection("vehicles").document(b.plate)
    v = ref.get()
    if not v.exists or not v.to_dict().get("active"):
        log(event="bind_rejected", plate=b.plate)
        return err(404, "unregistered_vehicle")
    ref.update({"bound_device_id": b.device_id})
    return {"plate": b.plate, **v.to_dict(), "bound_device_id": b.device_id}


@app.post("/incidents")
def incidents(i: Incident):
    iid = "INC-" + uuid.uuid4().hex[:6].upper()
    db.collection("incidents").document(iid).set(
        {"type": i.type, "severity_note": i.severity_note, "created_at": datetime.now(timezone.utc), "state": "open"})
    return {"incident_id": iid}


@app.post("/runs")
def runs(r: RunReq):
    if r.action == "end":
        ref = db.collection("runs").document(r.run_id or "-")
        if not ref.get().exists:
            return err(404, "unknown_run")
        ref.update({"state": "ended"})
        log(event="run_ended", run_id=r.run_id)
        return {"run_id": r.run_id, "state": "ended"}
    if r.action != "start" or not (r.plate and r.incident_id and r.corridor):
        return err(400, "bad_request", detail="start needs plate, incident_id, corridor")
    v = db.collection("vehicles").document(r.plate).get()
    inc = db.collection("incidents").document(r.incident_id).get()
    if not (v.exists and v.to_dict().get("active")):
        return err(403, "unregistered_vehicle")
    if not (inc.exists and inc.to_dict().get("state") == "open"):
        return err(403, "no_active_incident")
    run_id = "run-" + uuid.uuid4().hex[:8]
    db.collection("runs").document(run_id).set({
        "vehicle_plate": r.plate, "vehicle_type": v.to_dict()["type"], "incident_id": r.incident_id,
        "corridor": r.corridor, "destination": r.destination, "source": r.source, "state": "en_route",
        "patient_on_board": False, "brief_fired": False, "started_at": datetime.now(timezone.utc)})
    log(event="run_started", run_id=run_id, plate=r.plate)
    return {"run_id": run_id}


def _extract_and_log(t: Triage):
    """Returns (run, fields, entry_ref) or a JSONResponse error."""
    run_ref = db.collection("runs").document(t.run_id)
    run = run_ref.get()
    if not run.exists:
        return err(404, "unknown_run")
    run = run.to_dict()
    audio = base64.b64decode(t.audio_b64) if t.audio_b64 else None
    if not (audio or t.text):
        return err(400, "bad_request", detail="audio_b64 or text required")
    try:
        fields = extract(audio, t.mime, t.text, t.vehicle_type or run["vehicle_type"], t.lang_hint, run_id=t.run_id)
    except ExtractionFailed:
        log(event="extraction_failed", run_id=t.run_id)
        return err(422, "extraction_failed", fallback="form")
    coll = run_ref.collection("log")
    n = len(list(coll.stream()))  # ponytail: count-based index, racy under concurrent writers
    coll.document(str(n)).set({
        "t": datetime.now(timezone.utc), "kind": t.kind or ("voice" if audio else "form"),
        "transcript_en": fields["transcript_en"], "fields": fields, "confirmed": False})
    return run, fields, run_ref, n


@app.post("/triage")
def triage(t: Triage):
    out = _extract_and_log(t)
    if isinstance(out, JSONResponse):
        return out
    run, fields, run_ref, _ = out
    vtype = t.vehicle_type or run["vehicle_type"]
    tier = acuity.tier({**fields, "incident_id": run.get("incident_id")}, vtype)
    run_ref.update({"acuity_tier": tier})
    log(event="triage", run_id=t.run_id, suggested_tier=tier)
    return {"fields": fields, "transcript_en": fields["transcript_en"], "suggested_tier": tier}


@app.post("/log")
def log_entry(t: Triage):
    out = _extract_and_log(t)
    if isinstance(out, JSONResponse):
        return out
    _, fields, _, n = out
    return {"n": n, "transcript_en": fields["transcript_en"], "fields": fields, "confirmed": False}


@app.post("/runs/{run_id}/confirm")
def confirm(run_id: str, c: Confirm):
    if c.tier not in TIERS:
        return err(400, "bad_tier", detail=sorted(TIERS))
    ref = db.collection("runs").document(run_id)
    if not ref.get().exists:
        return err(404, "unknown_run")
    ref.update({"confirmed_tier": c.tier, "patient_on_board": True})
    log(event="tier_confirmed", run_id=run_id, tier=c.tier)
    return {"run_id": run_id, "confirmed_tier": c.tier, "patient_on_board": True}


@app.post("/brief")
def brief():
    return todo("brief")


@app.post("/location")
def location():
    return todo("location")


@app.post("/ack")
def ack():
    return todo("ack")
