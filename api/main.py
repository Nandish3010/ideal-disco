import base64
import hmac
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.api_core.exceptions import GoogleAPIError
from google.cloud.firestore import DELETE_FIELD, SERVER_TIMESTAMP, Increment, Query, transactional
from google.cloud.firestore_v1.base_query import FieldFilter
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

import aar
import acuity
import agent
import apidoc
import brief
import copnote
import desk_reads
import gemini
import leadtime
import priority
import production
import push
import ratelimit
import report
import routes_api
import telemetry
import tokens
from apidoc import (
    AckOut,
    AfterActionOut,
    Bound,
    BriefOut,
    ConfirmOut,
    CopNoteOut,
    DutyOut,
    Health,
    HospitalDutyOut,
    HousekeepingOut,
    IncidentOut,
    LocationOut,
    LogOut,
    RoutingOut,
    RunOut,
    TriageOut,
    ex,
    meta,
)
from corridor import CORRIDORS, MATCH_M, SCENARIOS, bearing, distance_m, junctions_ahead, locate
from firestore_client import db
from gemini import ExtractionFailed, extract, offline
from hospitals import by_id
from logctx import log, request_id
from signal_adapter import SimAdapter
from tts import speak, store_photo, translate

VERSION = (os.environ.get("GIT_SHA") or "dev")[:7]  # the deployed commit; "dev" when run from a checkout
app = FastAPI(
    title="Emergency Green Corridor API",
    version=VERSION,
    description=apidoc.DESCRIPTION,
    openapi_tags=apidoc.TAGS,
    docs_url="/docs",
    openapi_url="/openapi.json",
    redoc_url=None,
)
apidoc.install_openapi(app)
if offline():
    log(event="offline_ai")
ORIGINS = [
    "https://green-corridor-2026.web.app",
    "https://green-corridor-2026.firebaseapp.com",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    *(o.strip() for o in os.environ.get("EXTRA_ORIGINS", "").split(",") if o.strip()),
]
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
TIERS = {"critical", "urgent", "stable", "fire", "fire_with_trapped", "police", "police_with_incident"}


def err(status: int, code: str, detail: str = "", headers: dict | None = None, **kw) -> JSONResponse:
    """The one error envelope: {"error": code, "detail": text}, plus any extra keys a client reads (state, fallback)."""
    return JSONResponse(
        {"error": code, "detail": detail or code.replace("_", " "), **kw}, status_code=status, headers=headers
    )


def deny(token: str, *hashes: str | None) -> JSONResponse | None:
    """401 device_token_required / 403 device_token_mismatch unless `token` is one of the stored hashes."""
    p = tokens.problem(token, list(hashes))
    return err(p[0], p[1]) if p else None


def deny_run(token: str, run: dict) -> JSONResponse | None:
    """The token must be the one handed out when the run's vehicle was bound."""
    if tokens.disabled():
        return None
    v = db.collection("vehicles").document(run.get("vehicle_plate") or "-").get().to_dict() or {}
    return deny(token, v.get("device_token_hash"))


def deny_run_or_hospital(token: str, run: dict) -> JSONResponse | None:
    """The run's vehicle token, or the token of any hospital desk that signed in (POST /hospital/duty)."""
    if tokens.disabled():
        return None
    v = db.collection("vehicles").document(run.get("vehicle_plate") or "-").get().to_dict() or {}
    desks = [d.to_dict().get("device_token_hash") for d in db.collection("hospital_duty").stream()]
    return deny(token, v.get("device_token_hash"), *desks)


def duty_hash(jid: str) -> str | None:
    """sha256 of the token the cop on duty at this junction (`blr_j3`) was given; None when off duty or never on."""
    d = db.collection("duty").document(jid).get().to_dict() or {}
    return d.get("device_token_hash") if d.get("on") else None


app.middleware("http")(
    production.guard
)  # registered before request_context so a refusal still gets a request id and an access line
app.include_router(desk_reads.router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Request id (X-Request-Id or a new uuid4) on every log line and the response; one access line per request. The
    per-IP rate limit comes first: 429 `rate_limited` with Retry-After."""
    rid = (request.headers.get("X-Request-Id") or str(uuid.uuid4()))[:64]
    token = request_id.set(rid)
    t0 = time.perf_counter()
    # Cloud Run appends the connecting address to X-Forwarded-For, so the last entry is the one a caller cannot forge
    ip = request.headers.get("X-Forwarded-For", "").split(",")[-1].strip() or (
        request.client.host if request.client else "-"
    )
    wait_s = await run_in_threadpool(
        ratelimit.retry_after, ip, request.url.path
    )  # a Firestore transaction: off the event loop
    try:
        if wait_s is None:
            resp = await call_next(request)
        else:
            resp = err(429, "rate_limited")
            resp.headers["Retry-After"] = str(wait_s)
    except Exception as e:
        log(event="unhandled_error", path=request.url.path, error=type(e).__name__, detail=str(e)[:200])
        resp = err(500, "internal_error")
    resp.headers["X-Request-Id"] = rid
    log(
        event="request",
        method=request.method,
        path=request.url.path,
        status=resp.status_code,
        ms=round((time.perf_counter() - t0) * 1000),
    )
    request_id.reset(token)
    return resp


# added last so it is outermost: even a 500 from request_context carries the CORS headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)
telemetry.setup(
    app
)  # after the middleware above, so the request span is outermost; a no-op unless OTEL_ENABLED=1


@app.exception_handler(GoogleAPIError)
def firestore_down(request, exc):
    log(event="firestore_error", path=request.url.path, error=type(exc).__name__, detail=str(exc)[:200])
    return err(503, "store_unavailable", "Firestore is unavailable")


@app.exception_handler(RequestValidationError)
def invalid_request(request, exc):
    return err(
        422,
        "validation_error",
        "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()),
    )


@app.exception_handler(StarletteHTTPException)
def http_error(request, exc):
    return err(
        exc.status_code,
        {400: "bad_request", 404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error"),
        str(exc.detail),
        headers=exc.headers,
    )


class Bind(BaseModel):
    model_config = ex(
        {"plate": "KA01AB1234", "device_id": "dev-1"},
    )
    plate: str
    device_id: str


class Incident(BaseModel):
    model_config = ex(
        {"type": "cardiac", "severity_note": "Synthetic demo incident"},
    )
    type: str
    severity_note: str = ""


class RunReq(BaseModel):
    model_config = ex(
        {
            "action": "start",
            "plate": "KA01AB1234",
            "incident_id": "INC-4BC6E7",
            "corridor": "blr",
            "source": "gps",
        },
        {"action": "end", "run_id": "run-1a2b3c4d"},
        **{  # a start needs these three (400 bad_request otherwise); the schema says so, so a client can tell
            "if": {"properties": {"action": {"const": "start"}}},
            "then": {
                "required": ["plate", "incident_id", "corridor"],
                "properties": {
                    k: {"type": "string", "minLength": 1} for k in ("plate", "incident_id", "corridor")
                },
            },
        },
    )
    action: str = Field(json_schema_extra={"enum": ["start", "end"]})  # anything else is 400 bad_request
    plate: str | None = None
    incident_id: str | None = None
    corridor: str | None = None
    destination: dict | None = None
    source: str = "gps"
    run_id: str | None = None
    scenario: str | None = None  # a data/scenarios/<name>.json replay: recorded spans, no Routes calls


class Triage(BaseModel):
    model_config = ex(
        {"run_id": "run-amb-1", "vehicle_type": "ambulance", "text": "chest pain, BP 85 over 50"},
        {"run_id": "run-amb-1", "vehicle_type": "ambulance", "audio_b64": "UklGRg==", "mime": "audio/webm"},
        anyOf=[  # 400 bad_request otherwise
            {"required": [k], "properties": {k: {"type": "string", "minLength": 1}}}
            for k in ("audio_b64", "image_b64", "text")
        ],
    )
    run_id: str
    vehicle_type: str | None = None
    text: str | None = None
    audio_b64: str | None = None
    image_b64: str | None = None  # photo of a monitor or ECG strip; mime is then image/jpeg|png|webp
    mime: str | None = None
    lang_hint: str | None = None
    kind: str | None = None  # /log only


class Confirm(BaseModel):
    model_config = ex(
        {"tier": "critical"},
    )
    # anything else is 400 bad_tier; the enum is for the documentation only
    tier: str = Field(json_schema_extra={"enum": list[Any](sorted(TIERS))})


@app.get("/health", **meta("ops", "Liveness and active model", Health))
def health():
    return {"ok": True, "model": os.environ.get("GEMINI_MODEL")}


@app.post(
    "/vehicles/bind",
    **meta("dispatch", "Bind a device to a registered vehicle (mock registry)", Bound, 400, 404, 422),
)
def vehicles_bind(b: Bind):
    ref = db.collection("vehicles").document(b.plate)
    v = ref.get()
    if not v.exists or not v.to_dict().get("active"):
        log(event="bind_rejected", plate=b.plate)
        return err(404, "unregistered_vehicle")
    token, h = tokens.mint()  # a re-bind rotates it: the previous device's calls then get 403
    ref.update({"bound_device_id": b.device_id, "device_token_hash": h})
    doc = {k: x for k, x in v.to_dict().items() if k != "device_token_hash"}
    return {"plate": b.plate, **doc, "bound_device_id": b.device_id, "device_token": token}


@app.post("/incidents", **meta("dispatch", "Open an incident (mock dispatch console)", IncidentOut, 400, 422))
def incidents(i: Incident):
    iid = "INC-" + uuid.uuid4().hex[:6].upper()
    db.collection("incidents").document(iid).set(
        {"type": i.type, "severity_note": i.severity_note, "created_at": datetime.now(UTC), "state": "open"}
    )
    return {"incident_id": iid}


@app.post("/runs", **meta("runs", "Start or end a run", RunOut, 400, 401, 403, 404, 422))
def runs(r: RunReq, x_device_token: str = Header("", description=apidoc.TOKEN_DOC)):
    if r.action == "end":
        ref = db.collection("runs").document(r.run_id or "-")
        snap = ref.get()
        if not snap.exists:
            return err(404, "unknown_run")
        if bad := deny_run(x_device_token, snap.to_dict() or {}):
            return bad
        ref.update({"state": "ended", "ahead_ids": [], "ahead": {}})
        log(event="run_ended", run_id=r.run_id)
        return {"run_id": r.run_id, "state": "ended", "report": report.write(r.run_id, ref)}
    if r.action != "start" or not (r.plate and r.incident_id and r.corridor):
        return err(400, "bad_request", "start needs plate, incident_id, corridor")
    v = db.collection("vehicles").document(r.plate).get()
    inc = db.collection("incidents").document(r.incident_id).get()
    if not (v.exists and v.to_dict().get("active")):
        return err(403, "unregistered_vehicle")
    if bad := deny(x_device_token, v.to_dict().get("device_token_hash")):
        return bad
    if not (inc.exists and inc.to_dict().get("state") == "open"):
        return err(403, "no_active_incident")
    # one active run per vehicle: the new one supersedes. ponytail: equality-only query (no composite index), state filtered here
    for old in db.collection("runs").where(filter=FieldFilter("vehicle_plate", "==", r.plate)).stream():
        if old.to_dict().get("state") in LIVE:
            old.reference.update(
                {"state": "ended", "ended_reason": "superseded", "ahead_ids": [], "ahead": {}}
            )  # no report card
            log(event="run_superseded", run_id=old.id, plate=r.plate)
    dest = r.destination
    if dest is None and r.scenario and (c := CORRIDORS.get(r.corridor)):
        dest = c["hospital"]  # a replay is bound for the corridor hospital: the run card never reads "to —"
    run_id = "run-" + uuid.uuid4().hex[:8]
    db.collection("runs").document(run_id).set(
        {
            "vehicle_plate": r.plate,
            "vehicle_type": v.to_dict()["type"],
            "incident_id": r.incident_id,
            "corridor": r.corridor,
            "destination": dest,
            "source": r.source,
            "state": "en_route",
            "patient_on_board": False,
            "brief_fired": False,
            "started_at": datetime.now(UTC),
            **({"scenario": r.scenario} if r.scenario else {}),
        }
    )
    log(event="run_started", run_id=run_id, plate=r.plate)
    return {"run_id": run_id}


MAX_EXTRACTS = 20  # triage + log calls per run: each one is a Gemini call
BRIEF_COOLDOWN_S = 600  # one brief per run per 10 minutes unless the caller asks to regenerate


def next_log_n(run_ref) -> int:
    """The run's next log number, 1-based, from runs/{id}.log_count bumped with Increment inside one transaction (Firestore
    retries on contention, so two writers never get the same n). A run with log entries but no counter yet counts them first."""

    @transactional  # built per call: the wrapper keeps retry state
    def bump(tx):
        snap = run_ref.get(transaction=tx).to_dict() or {}
        n = (
            snap["log_count"]
            if "log_count" in snap
            else len(list(run_ref.collection("log").stream(transaction=tx)))
        )
        tx.update(run_ref, {"log_count": Increment(1) if "log_count" in snap else n + 1})
        return n + 1

    return bump(db.transaction())


def _extract_and_log(t: Triage, token: str, interventions=False):
    """Returns (run, fields, run_ref, n, interventions, photo_url) or a JSONResponse error."""
    run_ref = db.collection("runs").document(t.run_id)
    run = run_ref.get()
    if not run.exists:
        return err(404, "unknown_run")
    run = run.to_dict()
    if bad := deny_run(token, run):
        return bad
    try:
        audio = base64.b64decode(t.audio_b64) if t.audio_b64 else None
        image = base64.b64decode(t.image_b64) if t.image_b64 else None
    except ValueError:  # binascii.Error: bad padding or length
        return err(400, "bad_request", "audio_b64 and image_b64 must be base64")
    if not (audio or image or t.text):
        return err(400, "bad_request", "audio_b64, image_b64 or text required")
    if image and (audio or t.mime not in IMAGE_MIMES):
        return err(400, "bad_request", f"image_b64 takes mime {sorted(IMAGE_MIMES)} and no audio_b64")
    if run.get("extract_calls", 0) >= MAX_EXTRACTS:
        return err(429, "run_cap_reached", f"at most {MAX_EXTRACTS} triage and log calls per run")
    run_ref.update(
        {"extract_calls": Increment(1)}
    )  # counted before the call: a failed extraction cost one too
    try:
        fields = extract(
            audio,
            t.mime,
            t.text,
            t.vehicle_type or run["vehicle_type"],
            t.lang_hint,
            run_id=t.run_id,
            interventions=interventions,
            image_bytes=image,
        )
    except ExtractionFailed:
        log(event="extraction_failed", run_id=t.run_id)
        return err(422, "extraction_failed", fallback="form")
    given = fields.pop("interventions", [])  # kept on the entry, not inside fields
    coll = run_ref.collection("log")
    n = next_log_n(run_ref)
    photo_url = (
        store_photo(image, t.mime or "image/jpeg", f"photos/{t.run_id}/{n}.jpg") if image else None
    )  # None: upload failed, entry still saved
    coll.document(str(n)).set(
        {
            "t": datetime.now(UTC),
            "kind": t.kind or ("photo" if image else "voice" if audio else "form"),
            "transcript_en": fields["transcript_en"],
            "fields": fields,
            "interventions": given,
            "confirmed": False,
            **({"photo_url": photo_url} if image else {}),
        }
    )
    return run, fields, run_ref, n, given, photo_url


@app.post(
    "/triage",
    **meta("triage", "Extract patient fields and suggest a tier", TriageOut, 400, 401, 403, 404, 422),
)
def triage(t: Triage, x_device_token: str = Header("", description=apidoc.TOKEN_DOC)):
    out = _extract_and_log(t, x_device_token)
    if isinstance(out, JSONResponse):
        return out
    run, fields, run_ref, _, _, photo_url = out
    vtype = t.vehicle_type or run["vehicle_type"]
    tier = acuity.tier({**fields, "incident_id": run.get("incident_id")}, vtype)
    run_ref.update({"acuity_tier": tier})
    log(event="triage", run_id=t.run_id, suggested_tier=tier)
    return {
        "fields": fields,
        "transcript_en": fields["transcript_en"],
        "suggested_tier": tier,
        **({"photo_url": photo_url} if t.image_b64 else {}),
    }


@app.post("/log", **meta("triage", "Append a log entry with interventions", LogOut, 400, 401, 403, 404, 422))
def log_entry(t: Triage, x_device_token: str = Header("", description=apidoc.TOKEN_DOC)):
    out = _extract_and_log(t, x_device_token, interventions=True)
    if isinstance(out, JSONResponse):
        return out
    _, fields, _, n, given, photo_url = out
    return {
        "n": n,
        "transcript_en": fields["transcript_en"],
        "fields": fields,
        "interventions": given,
        "confirmed": False,
        **({"photo_url": photo_url} if t.image_b64 else {}),
    }


@app.post(
    "/runs/{run_id}/confirm",
    **meta("runs", "Confirm the tier (the crew's one tap)", ConfirmOut, 400, 401, 403, 404, 422),
)
def confirm(
    run_id: str,
    c: Confirm,
    bg: BackgroundTasks,
    x_device_token: str = Header("", description=apidoc.TOKEN_DOC),
):
    if c.tier not in TIERS:
        return err(400, "bad_tier", "tier must be one of: " + ", ".join(sorted(TIERS)))
    ref = db.collection("runs").document(run_id)
    snap = ref.get()
    if not snap.exists:
        return err(404, "unknown_run")
    if bad := deny_run(x_device_token, snap.to_dict() or {}):
        return bad
    ref.update({"confirmed_tier": c.tier, "patient_on_board": True})
    log(event="tier_confirmed", run_id=run_id, tier=c.tier)
    bg.add_task(
        agent.apply, ref
    )  # hospital routing agent after the response (Cloud Run runs with --no-cpu-throttling); the UI reads runs/{id}.routing live
    return {"run_id": run_id, "confirmed_tier": c.tier, "patient_on_board": True, "routing": None}


class RouteReq(BaseModel):
    model_config = ex(
        {"run_id": "run-amb-1"},
    )
    run_id: str


@app.post(
    "/route",
    **meta("hospital", "Re-run the hospital routing agent", RoutingOut, 400, 401, 403, 404, 409, 422),
)
def route(r: RouteReq, x_device_token: str = Header("", description=apidoc.TOKEN_DOC)):
    ref = db.collection("runs").document(r.run_id)
    if not (snap := ref.get()).exists:
        return err(404, "unknown_run")
    if bad := deny_run(x_device_token, snap.to_dict() or {}):
        return bad
    if (snap.to_dict() or {}).get("state") in ("arrived", "ended"):
        return err(409, "run_not_en_route", "the run has arrived or ended; its hospital is already decided")
    return agent.apply(ref) or err(
        409, "not_routable", "needs a confirmed ambulance run on a corridor with a roster"
    )


def write_brief(run_id, run_ref, run, entries):
    """Generate from the log and store briefs/{run_id}; marks the run's brief as fired. Raises ExtractionFailed."""
    b, model = brief.generate(run, entries, run_id=run_id)
    doc = {**b, "disclaimer": brief.DISCLAIMER, "generated_at": datetime.now(UTC), "model": model}
    db.collection("briefs").document(run_id).set(doc)
    run_ref.update({"brief_fired": True, "brief_due": False})
    log(event="brief_written", run_id=run_id, model=model)
    return doc


def log_entries(run_ref):
    return [d.to_dict() for d in sorted(run_ref.collection("log").stream(), key=lambda d: int(d.id))]


class BriefReq(BaseModel):
    model_config = ex(
        {"run_id": "run-amb-1", "regenerate": False},
    )
    run_id: str
    regenerate: StrictBool = (
        False  # a brief written in the last 10 minutes is refused (429) unless this is set
    )


@app.post("/brief", **meta("triage", "Generate the hospital brief", BriefOut, 400, 401, 403, 404, 422, 502))
def brief_endpoint(b: BriefReq, x_device_token: str = Header("", description=apidoc.TOKEN_DOC)):
    run_ref = db.collection("runs").document(b.run_id)
    run = run_ref.get()
    if not run.exists:
        return err(404, "unknown_run")
    if b.regenerate and (bad := deny_run_or_hospital(x_device_token, run.to_dict() or {})):
        return bad
    entries = log_entries(run_ref)
    if not entries:
        return err(422, "no_log_entries", "nothing to brief yet")
    old = db.collection("briefs").document(b.run_id).get()
    if not b.regenerate and old.exists and (made := (old.to_dict() or {}).get("generated_at")):
        wait = BRIEF_COOLDOWN_S - (datetime.now(UTC) - made).total_seconds()
        if wait > 0:
            return err(
                429,
                "brief_cooldown",
                "one brief per run per 10 minutes; send regenerate to replace it",
                retry_after_s=round(wait),
            )
    try:
        return write_brief(b.run_id, run_ref, run.to_dict(), entries)
    except ExtractionFailed:
        log(event="brief_error", run_id=b.run_id, via="endpoint")
        return err(502, "brief_failed")


@app.post(
    "/runs/{run_id}/after-action",
    **meta("runs", "After-action report of a finished run", AfterActionOut, 401, 403, 404, 409, 422, 502),
)
def after_action(
    run_id: str, regenerate: bool = False, x_device_token: str = Header("", description=apidoc.TOKEN_DOC)
):
    run_ref = db.collection("runs").document(run_id)
    run = run_ref.get()
    if not run.exists:
        return err(404, "unknown_run")
    if regenerate and (bad := deny_run_or_hospital(x_device_token, run.to_dict() or {})):
        return bad
    r = run.to_dict()
    if r.get("state") not in ("ended", "arrived"):
        return err(409, "run_not_finished", "the report is written once the run has ended or arrived")
    stored = db.collection("after_action").document(run_id)
    if not regenerate and (old := stored.get()).exists:
        return old.to_dict()
    rep = db.collection("reports").document(run_id).get()
    alerts = [d.to_dict() for d in run_ref.collection("alerts").stream()]
    try:
        body, model = aar.generate(
            r, log_entries(run_ref), alerts, rep.to_dict() if rep.exists else None, r.get("routing"), run_id
        )
    except ExtractionFailed:
        log(event="aar_error", run_id=run_id)
        return err(502, "after_action_failed")
    doc = {**body, "generated_at": datetime.now(UTC), "model": model}
    stored.set(doc)
    log(event="aar_written", run_id=run_id, model=model)
    return doc


IDEMPOTENCY_TTL_S = 600
IDEMPOTENCY_KEY = r"^[A-Za-z0-9_.:-]{1,128}$"  # also a valid Firestore document id (no "/")


class Loc(BaseModel):
    model_config = ex(
        {
            "run_id": "run-amb-1",
            "lat": 12.9197,
            "lng": 77.6204,
            "speed_mps": 13.2,
            "heading": 231,
            "t": "2026-10-05T09:02:30Z",
            "source": "sim",
            "tick_id": "tick-0042",
        },
    )
    run_id: str
    lat: StrictFloat = Field(ge=-90, le=90)  # strict: true/false are not numbers
    lng: StrictFloat = Field(ge=-180, le=180)
    speed_mps: StrictFloat = Field(ge=0)
    heading: StrictFloat | None = None  # degrees; derived from the previous tick when absent
    t: datetime | None = None  # tick time; server time when absent
    source: str = Field("gps", pattern="^(gps|sim)$")
    tick_id: str | None = Field(
        default=None,
        pattern=IDEMPOTENCY_KEY,
        description="Idempotency key; the Idempotency-Key header wins.",
    )  # a repeat within IDEMPOTENCY_TTL_S returns the first response


LIVE = {"en_route", "off_route", "stale"}  # ticks revive stale and off_route runs; ended/arrived get 403
OFF_ROUTE_M, STALE_S, BRIEF_ETA_S, MIN_TICK_GAP_S, ARRIVE_M = 80, 30, 300, 5, 100
BRIEF_MIN_M, PREPARE_MIN_JAM_M = (
    500,
    50,
)  # brief needs a junction passed or this far driven; PREPARE needs a queue this long
LABEL = {"ambulance": "AMBULANCE", "fire": "FIRE ENGINE", "police": "POLICE"}
COMPASS = {
    "N": "north",
    "NE": "north-east",
    "E": "east",
    "SE": "south-east",
    "S": "south",
    "SW": "south-west",
    "W": "west",
    "NW": "north-west",
}


def alert_to_fire(stage, s, jam_m):
    """Alerts: PREPARE once, UPDATE if the queue grew > 100 m, STOP once. s: the junction's alert_state so far."""
    s = s or {}
    if stage == "STOP" and not s.get("stop"):
        return "STOP"
    if stage == "PREPARE" and not s.get("prepare") and jam_m >= PREPARE_MIN_JAM_M:
        return "PREPARE"
    if stage == "PREPARE" and not s.get("stop") and jam_m > s.get("jam_m", 0) + 100:
        return "UPDATE"
    return None


def claim_alert(run_ref, jid, stage, fire, jam_m):
    """The next alert number for (run, junction, stage), or None when it already fired. The check and the write to
    runs/{id}.alert_state / alert_count are one transaction, so two concurrent ticks never both fire one alert."""

    @transactional
    def claim(tx):
        cur = run_ref.get(transaction=tx).to_dict() or {}
        s = (cur.get("alert_state") or {}).get(jid) or {}
        if alert_to_fire(stage, s, jam_m) != fire:
            return None
        n = cur.get("alert_count", 0)
        tx.update(
            run_ref,
            {
                f"alert_state.{jid}": {
                    "prepare": True,
                    "stop": bool(s.get("stop")) or fire == "STOP",
                    "jam_m": jam_m,
                },
                "alert_count": n + 1,
            },
        )
        return n

    return claim(db.transaction())


def alert_text(run, stage, jam_m, approach, exit_move, eta_s):
    vt = run["vehicle_type"]
    tier = run.get("confirmed_tier") or run.get("acuity_tier") or ("unconfirmed" if vt == "ambulance" else "")
    tier = tier.replace("_", " ").upper().replace(vt.upper(), "").strip()
    who = " ".join(x for x in (LABEL[vt], tier) if x)
    queue = f"{round(jam_m)} m queue" if jam_m else "no queue"
    move = "going STRAIGHT" if exit_move == "straight" else f"turning {exit_move.upper()}"
    arrives = f"{round(eta_s)} s" if eta_s < 60 else f"{round(eta_s / 60)} min"
    head = {"STOP": "STOP CROSS TRAFFIC · ", "UPDATE": "UPDATE · "}.get(stage, "")
    return f"{head}{who} · {queue} on your {COMPASS.get(approach, approach)} approach · {move} · arrives in {arrives}"


def defer(bg: BackgroundTasks, fn, *args) -> None:
    """Run fn after the response is sent (Cloud Run runs with --no-cpu-throttling, so the work continues). An error is
    logged, never raised: the tick it belongs to has already been answered."""

    def run():
        try:
            fn(*args)
        except Exception as e:
            log(event="background_error", task=fn.__name__, error=type(e).__name__, detail=str(e)[:200])

    bg.add_task(run)


def finish_alert(alert_ref, text, lang, path):
    """Voice for an alert already written: speech and the spoken-language text patched in (None, None when synthesis fails)."""
    audio_url, text_local = speak(text, lang, path)
    alert_ref.update({"audio_url": audio_url, "text_local": text_local})
    push.send_alert(alert_ref, audio_url)  # FCM to the cop on duty; failures are logged inside


def brief_from_tick(run_id, run_ref, run, entries):
    """The brief a tick found due, generated after that tick was answered. On Gemini failure brief_due stays true."""
    try:
        write_brief(run_id, run_ref, run, entries)
    except ExtractionFailed:
        log(event="brief_error", run_id=run_id, via="location")


def rationale(jid, seq, lang):
    """The phase's 'why this order' line, English plus the junction language. The stored text is the deterministic
    template; Gemini only paraphrases it, and its rewrite replaces the template only if valid_paraphrase accepts it.
    Always rewritten (deleted when fewer than 2 vehicles) so a stale line never outlives its sequence; with 2 or more it
    is written to `last_sequence` too, which a later single-vehicle phase leaves in place."""
    keys = ["phase"] + (
        ["last_sequence"] if len(seq) >= 2 else []
    )  # last_sequence follows the newest multi-vehicle phase
    out: dict[str, Any] = {f"{k}.{f}": DELETE_FIELD for k in keys for f in ("rationale", "rationale_local")}
    if len(seq) >= 2 and not offline():
        facts = priority.rationale_facts(seq)
        en = priority.template_rationale(facts)
        try:
            alt = gemini.paraphrase_sequence(en, facts)
            if priority.valid_paraphrase(alt, en):
                en = alt
            else:
                log(event="rationale_template", junction_id=jid, rejected=alt[:200])
        except (genai_errors.APIError, GoogleAPIError, httpx.TimeoutException) as e:
            log(event="rationale_error", junction_id=jid, error=type(e).__name__, detail=str(e)[:200])
        for k in keys:
            out[f"{k}.rationale"] = en
        try:
            local = translate(en, lang)
            for k in keys:
                out[f"{k}.rationale_local"] = local
        except (genai_errors.APIError, GoogleAPIError) as e:
            log(event="rationale_error", junction_id=jid, error=type(e).__name__, detail=str(e)[:200])
    db.collection("junctions").document(jid).update(out)


def cop_blocked(jid, now) -> bool:
    """True while a cop's `cannot_clear` report on this junction is in force (copnote.BLOCK_S)."""
    until = (db.collection("junctions").document(jid).get().to_dict() or {}).get("cop_block_until")
    return bool(until and until > now)


def preempt(run_id, run, jid, approach, eta_s, clear_s, stage, lang, bg, blocked=False):
    me = priority.contender(run_id, run, eta_s, approach)
    if me is None:
        return None
    rows = [me]
    for d in (
        db.collection("runs").where(filter=FieldFilter("ahead_ids", "array_contains", jid)).limit(20).stream()
    ):
        r = d.to_dict()
        if d.id != run_id and r.get("state") == "en_route" and jid in (r.get("ahead") or {}):
            c = priority.contender(d.id, r, r["ahead"][jid]["eta_s"], r["ahead"][jid]["approach"])
            if c:
                rows.append(c)
    seq = priority.sequence(rows)
    SimAdapter(db).request_green(
        jid,
        seq[0]["approach"],
        clear_s + 30 + seq[-1]["offset_s"] + priority.spread_s(seq),
        [c["run_id"] for c in seq],
        [{"run_id": c["run_id"], "offset_s": c["offset_s"], "approach": c["approach"]} for c in seq],
        blocked,
    )
    sequence = [{"run_id": c["run_id"], "offset_s": c["offset_s"]} for c in seq]
    defer(bg, rationale, jid, seq, lang)  # Gemini + translation: patched onto the phase after the response
    db.collection("audit").add(
        {
            "run_id": run_id,
            "junction_id": jid,
            "action": "preempt_requested",
            "stage": stage,
            "approach": seq[0]["approach"],
            "sequence": sequence,
            "at": datetime.now(UTC),
        }
    )
    log(event="preempt_requested", run_id=run_id, junction_id=jid, sequence=sequence)
    return sequence


def mark_stale(now, skip) -> int:
    """Runs with no tick for 30 s go stale; returns how many. Runs on every tick and from /housekeeping. ponytail: newest 20
    below the cutoff."""
    stale = 0
    q = (
        db.collection("runs")
        .where(filter=FieldFilter("last_tick_at", "<", now - timedelta(seconds=STALE_S)))
        .order_by("last_tick_at", direction=Query.DESCENDING)
        .limit(20)
    )
    for d in q.stream():
        if d.id != skip and d.to_dict().get("state") == "en_route":
            d.reference.update({"state": "stale", "ahead_ids": []})
            log(event="run_stale", run_id=d.id)
            stale += 1
    return stale


ESCALATE_S = 20
ROUTE_TTL_S = (
    20  # one Routes call per run this often: vehicle -> hospital, every junction ahead is read out of it
)
PASS_SLACK_M = 15  # projected this far beyond a junction's route offset counts as passed (GPS slack)


def escalate(now, mine, others) -> int:
    """Alerts older than 20 s with no ACK are flagged and audited; returns how many. A tick checks this run's alerts plus
    the runs it shared a preemption sequence with (those still en_route)."""
    ids = list(mine)
    for rid in others:
        r = db.collection("runs").document(rid).get()
        if r.exists and r.to_dict().get("state") == "en_route":
            ids.append(rid)
    flagged = 0
    for rid in ids:
        q = (
            db.collection("runs")
            .document(rid)
            .collection("alerts")
            .where(filter=FieldFilter("acked_at", "==", None))
            .where(filter=FieldFilter("escalated", "==", False))
        )
        for d in q.stream():
            a = d.to_dict()
            if a.get("created_at") is None or (now - a["created_at"]).total_seconds() <= ESCALATE_S:
                continue
            d.reference.update({"escalated": True, "escalated_at": SERVER_TIMESTAMP})
            db.collection("audit").add(
                {
                    "run_id": rid,
                    "junction_id": a["junction_id"],
                    "action": "escalation",
                    "alert_n": int(d.id),
                    "stage": a["stage"],
                    "at": now,
                }
            )
            log(event="escalation", run_id=rid, junction_id=a["junction_id"], alert_n=int(d.id))
            flagged += 1
    return flagged


@app.post(
    "/housekeeping",
    **meta("ops", "Stale and escalation sweep (Cloud Scheduler)", HousekeepingOut, 403, 404, 422),
)
def housekeeping(x_housekeeping_token: str = Header("", description="Must equal env HOUSEKEEPING_TOKEN.")):
    """Cloud Scheduler, once a minute: the stale and escalation sweeps without waiting for a tick. 404 while
    HOUSEKEEPING_TOKEN is unset, 403 on a wrong token."""
    token = os.environ.get("HOUSEKEEPING_TOKEN")
    if not token:
        return err(404, "not_found")
    if not hmac.compare_digest(x_housekeeping_token.encode(), token.encode()):
        return err(403, "forbidden")
    now = datetime.now(UTC)
    stale = mark_stale(now, None)
    # ponytail: first 200 live runs; stale ones included, their alerts still wait for an ACK
    live = [
        d.id
        for d in db.collection("runs")
        .where(filter=FieldFilter("state", "in", sorted(LIVE)))
        .limit(200)
        .stream()
    ]
    return {"stale": stale, "escalated": escalate(now, live, []), "runs_checked": len(live)}


@app.post(
    "/location",
    **meta(
        "corridor",
        "Location tick: alerts, preemption and ETA",
        LocationOut,
        400,
        401,
        403,
        404,
        422,
        headers={
            "Idempotent-Replayed": {
                "description": "true when the stored response of an earlier tick with the same key is returned.",
                "schema": {"type": "string"},
            }
        },
    ),
)
def location(
    loc: Loc,
    bg: BackgroundTasks,
    x_device_token: str = Header("", description=apidoc.TOKEN_DOC),
    idempotency_key: str | None = Header(
        None,
        pattern=IDEMPOTENCY_KEY,
        description="A repeat with the same key within 10 minutes returns the first response and writes nothing.",
    ),
):
    ref = db.collection("runs").document(loc.run_id)
    snap = ref.get()
    if not snap.exists:
        return err(404, "unknown_run")
    run = snap.to_dict()
    if bad := deny_run(x_device_token, run):
        return bad
    now = datetime.now(UTC)
    key = idempotency_key or loc.tick_id
    idem = None
    if key:  # a retried tick whose response was lost: answer from the first one, write nothing
        idem = db.collection("idempotency").document(loc.run_id).collection("keys").document(key)
        done = idem.get().to_dict()
        if done and done["expires_at"] > now:
            log(event="location_replayed", run_id=loc.run_id)
            return JSONResponse(done["response"], headers={"Idempotent-Replayed": "true"})
    if run["state"] not in LIVE:
        return err(403, "run_not_active", state=run["state"])
    corridor = CORRIDORS.get(run.get("corridor"))
    if corridor is None:
        return err(400, "unknown_corridor", str(run.get("corridor")))
    t = loc.t if loc.t and loc.t.tzinfo else (loc.t.replace(tzinfo=UTC) if loc.t else now)
    me = (loc.lat, loc.lng)
    first = run.get("first_tick_at") is None

    # tick history: last 12, at most one per 5 s so they span ~60 s
    prev = run.get("ticks") or []
    last = prev[-1] if prev else None
    heading = loc.heading
    if heading is None:
        heading = (
            bearing((last["lat"], last["lng"]), me)
            if last and distance_m((last["lat"], last["lng"]), me) > 5
            else run.get("heading")
        )
    tick = {"t": t, "lat": loc.lat, "lng": loc.lng, "speed_mps": loc.speed_mps}
    ticks = (prev[:-1] if last and (t - last["t"]).total_seconds() < MIN_TICK_GAP_S else prev)[-11:] + [tick]
    window = [k["speed_mps"] for k in ticks if (t - k["t"]).total_seconds() <= 60]
    observed = sum(window) / len(window)

    # hospital route: ETA, polyline for junction and off-route detection, and (TRAFFIC_ON_POLYLINE) the speed spans of the
    # whole route, which the junctions below slice. While off_route the old polyline stays pinned so the state holds until
    # the vehicle rejoins it (the route cache is shared through Firestore, so every instance pins the same one).
    scenario = (
        run.get("scenario") in SCENARIOS
    )  # replays follow the corridor config, not Google's road choice
    # a replay keeps its own destination (routing is recorded, not applied)
    dest = (
        (None if scenario else by_id((run.get("routing") or {}).get("hospital_id")))
        or run.get("destination")
        or corridor["hospital"]
    )
    # route_override (set by the re-planner): a live run follows Routes' first alternative from now on, a replay's ETA moves
    # by the alternative's recorded delta (the replay driver follows route_override.points)
    ov = run.get("route_override") or {}
    if scenario:
        hosp = {
            "polyline_points": [],
            "steps": [],
            "age_s": 0,
            "duration_s": distance_m(me, (dest["lat"], dest["lng"])) / max(observed, 3)
            + ov.get("eta_delta_s", 0),
        }
    else:
        for alt in (1, 0) if ov else (0,):  # no usable alternative any more: the plain route again
            hosp = routes_api.traffic_to_point(
                me,
                (dest["lat"], dest["lng"]),
                key=(f"{loc.run_id}-alt" if alt else loc.run_id, "route"),
                ttl=1e9 if run["state"] == "off_route" else ROUTE_TTL_S,
                steps=True,
                alt=alt,  # ponytail: asked again from wherever the vehicle is, so it can drift to another alternative
                run_id=loc.run_id,
                junction_id=None,
            )
            if hosp["duration_s"] is not None:
                break
    pts = hosp["polyline_points"]
    v_along, off = locate(pts, me) if pts else (0.0, 0)
    route_m = sum(distance_m(a, b) for a, b in zip(pts, pts[1:], strict=False))
    pace = (
        hosp["duration_s"] / route_m if hosp["duration_s"] and route_m else None
    )  # traffic-aware s per metre
    state = "off_route" if off > OFF_ROUTE_M else "en_route"
    eta_h = run.get("eta_hospital_s")
    if hosp["duration_s"] is not None and hosp["age_s"] < 120:  # older means a pinned route: not an ETA
        eta_h = round(max(hosp["duration_s"] - hosp["age_s"], 0))
    out = {
        "state": state,
        "next_junction": None,
        "approach": None,
        "jam_m": None,
        "eta_s": None,
        "stage": None,
        "exit_move": None,
        "eta_hospital_s": eta_h,
        "alerts_fired": [],
        "brief_due": bool(run.get("brief_due")),
        "observed_speed_60s": round(observed, 1),
        "traffic": None,
    }
    upd = {
        "ticks": ticks,
        "last_tick_at": now,
        "source": loc.source,
        "state": state,
        "heading": heading,
        "eta_hospital_s": eta_h,
        "next_junction_id": None,
    }
    if first:
        upd["first_tick_at"] = t  # the drive starts at the first tick, not at run creation (report card)

    # every junction ahead is evaluated, not just the next: a long queue needs the cop warned minutes before the vehicle
    # reaches the junction, while nearer junctions are still to come. No Routes call per junction: each reads its queue
    # out of the run's one route call.
    # route_index: corridor index of the next junction (= how many are passed, a prefix of corridor order). It only grows,
    # so a junction never comes back as "next" however the route or the GPS wobbles.
    ri = max(run.get("route_index", 0), len(run.get("passed_junctions") or []))
    order = {f"{corridor['id']}_{j['id']}": i for i, j in enumerate(corridor["junctions"])}
    ahead = (
        [
            (j, ap)
            for j, ap in junctions_ahead(corridor, loc.lat, loc.lng, heading, pts)
            if order[j["doc_id"]] >= ri
        ]
        if state == "en_route"
        else []
    )
    alerts = run.get("alert_state") or {}
    upd["ahead"], upd["ahead_ids"] = {}, []
    contenders = set(
        run.get("contenders") or []
    )  # run ids met in a preemption sequence; their alerts get escalation-checked too
    for j, ap in ahead:
        jid, jc, dist = j["doc_id"], (j["lat"], j["lng"]), j["ahead_m"]
        if scenario:  # recorded spans, no Routes call; a junction with none recorded is NORMAL
            rec = SCENARIOS[run["scenario"]].get("recorded_spans", {}).get(jid) or [{"intervals": []}]
            snap = next(
                (s for s in rec if s.get("approach") == ap["id"]), None
            )  # the run's own approach, not the corridor's
            if snap is None:
                snap = rec[0]
                if rec[0].get("approach"):
                    log(event="scenario_span_fallback", run_id=loc.run_id, junction_id=jid, approach=ap["id"])
            intervals, routes_eta, traffic = snap["intervals"], dist / max(observed, 3), "scenario"
        else:
            # the queue is the stretch of the route's speed spans up to this junction's stop line (the end of its approach
            # polyline, projected onto the route), at most 600 m back and never behind the vehicle; the ETA is the distance
            # at the route's average traffic-aware pace
            intervals = []
            if pts:
                end_m = locate(pts, tuple(ap["polyline"][-1]))[0]
                intervals = leadtime.slice_intervals(
                    hosp["intervals"], max(end_m - leadtime.JAM_LOOKBACK_M, v_along), end_m
                )
            traffic = "stale" if hosp["stale"] else "live"
            routes_eta = dist * pace if pace else dist / max(observed, 3)
        jam_m = leadtime.jam_metres(intervals)
        blocked = cop_blocked(jid, now)
        clear_s = leadtime.clear_seconds(jam_m) * (
            2 if blocked else 1
        )  # the cop said it cannot clear: warn earlier, hold longer
        with telemetry.span("leadtime"):  # not a decorator: the logger job image bundles leadtime.py alone
            eta_s = leadtime.blended_eta(routes_eta, dist, observed)
            stage = leadtime.stage(eta_s, clear_s)
        if stage is None and jam_m > 0 and jam_m >= dist - 25:  # vehicle is inside the queue: alert now
            stage = "PREPARE"
        if distance_m(me, jc) <= ap["radius_m"]:  # at the stop line
            stage = "STOP"
        if ap["bearing_err"] > 45:
            log(
                event="approach_bearing_mismatch",
                run_id=loc.run_id,
                junction_id=jid,
                approach=ap["id"],
                err=round(ap["bearing_err"]),
            )
        move = routes_api.exit_move(hosp["steps"], jc)
        upd["ahead"][jid] = {"eta_s": eta_s, "approach": ap["id"]}
        upd["ahead_ids"].append(jid)

        fire = alert_to_fire(stage, alerts.get(jid), jam_m)
        n = (
            claim_alert(ref, jid, stage, fire, jam_m) if fire else None
        )  # None: a concurrent tick already fired it
        if n is not None:
            text = alert_text(run, fire, jam_m, ap["id"], move, eta_s)
            alert_ref = ref.collection("alerts").document(str(n))
            alert_ref.set(
                {
                    "junction_id": jid,
                    "approach": ap["id"],
                    "stage": fire,
                    "jam_m": round(jam_m),
                    "eta_s": round(eta_s),
                    "exit_move": move,
                    "text": text,
                    "text_local": None,  # speech and the spoken-language text are patched in by finish_alert
                    "audio_url": None,
                    "acked_at": None,
                    "escalated": False,
                    "created_at": SERVER_TIMESTAMP,
                }
            )
            defer(
                bg,
                finish_alert,
                alert_ref,
                text,
                corridor["lang"],
                f"alerts/{loc.run_id}/{jid}/{fire}-{n}.mp3",
            )
            out["alerts_fired"].append({"junction": jid, "stage": fire})
            log(
                event="alert",
                run_id=loc.run_id,
                junction_id=jid,
                stage=fire,
                jam_m=round(jam_m),
                eta_s=round(eta_s),
            )
            seq = preempt(loc.run_id, run, jid, ap["id"], eta_s, clear_s, fire, corridor["lang"], bg, blocked)
            contenders.update(c["run_id"] for c in seq or [])
        if upd["next_junction_id"] is None:  # nearest junction ahead is what the response reports
            upd.update({"next_junction_id": jid, "next_approach": ap["id"], "next_eta_s": eta_s})
            out.update(
                {
                    "next_junction": jid,
                    "approach": ap["id"],
                    "jam_m": round(jam_m),
                    "eta_s": round(eta_s),
                    "stage": stage,
                    "exit_move": move,
                    "traffic": traffic,
                }
            )
    upd["last_eval"] = {
        k: out[k] for k in ("next_junction", "approach", "jam_m", "eta_s", "stage", "exit_move", "traffic")
    }

    # passed: a junction is passed once the step from the last tick went through its stop-line circle and the vehicle is out
    # of it again, or (a 5 s tick can jump the circle) once the vehicle's position along the route is past the junction's
    # offset on it. Passing one passes every earlier one (corridor order is route order).
    hi = ri - 1
    for i, j in enumerate(corridor["junctions"]):
        if i <= hi:
            continue
        jc = (j["lat"], j["lng"])
        crossed = last and locate([(last["lat"], last["lng"]), me], jc)[1] <= j["approaches"][0][
            "radius_m"
        ] < distance_m(me, jc)
        beyond = False
        if pts and state == "en_route":
            along, apart = locate(pts, jc)
            beyond = apart <= MATCH_M and v_along - along > PASS_SLACK_M
        if crossed or beyond:
            hi = i
    upd["route_index"] = hi + 1
    upd["passed_junctions"] = passed = [
        f"{corridor['id']}_{j['id']}" for j in corridor["junctions"][: hi + 1]
    ]

    # brief: ambulances only, once per run at ETA <= 300 s, and only once the run is under way (a junction passed or 500 m
    # driven; never a scenario run's first tick). Needs log entries, else retried next tick; on Gemini failure brief_due stays
    # true and the hospital's Regenerate button (POST /brief) takes over.
    entries = []
    upd["distance_m"] = round(
        run.get("distance_m", 0) + (distance_m((last["lat"], last["lng"]), me) if last else 0)
    )
    if (
        run["vehicle_type"] == "ambulance"
        and eta_h is not None
        and eta_h <= BRIEF_ETA_S
        and (passed or upd["distance_m"] >= BRIEF_MIN_M)
        and not (scenario and first)
        and not run.get("brief_fired")
        and not run.get("brief_due")
    ):
        entries = log_entries(ref)
        upd["brief_due"] = out["brief_due"] = bool(entries)
    upd["contenders"] = sorted(contenders - {loc.run_id})
    arrived = distance_m(me, (dest["lat"], dest["lng"])) <= ARRIVE_M
    if arrived:
        upd.update({"state": "arrived", "ahead_ids": [], "ahead": {}})
        out["state"] = "arrived"
    ref.update(upd)
    if entries:  # brief_due stays true in the response: the brief is being written after it
        defer(bg, brief_from_tick, loc.run_id, ref, run, entries)
    mark_stale(now, loc.run_id)
    escalate(now, [loc.run_id], upd["contenders"])
    if arrived:
        report.write(loc.run_id, ref)
    if (
        idem is not None
    ):  # expires_at: the 10 minute window, and the field a Firestore TTL policy on `keys` deletes by
        idem.set({"response": out, "expires_at": now + timedelta(seconds=IDEMPOTENCY_TTL_S)})
    return out


class Ack(BaseModel):
    model_config = ex(
        {"run_id": "run-amb-1", "junction_id": "blr_j3", "alert_n": 0, "device_id": "dev-cop-1"},
    )
    run_id: str
    alert_n: StrictInt
    junction_id: str
    device_id: str | None = None


@app.post("/ack", **meta("corridor", "Acknowledge an alert", AckOut, 400, 401, 403, 404, 422))
def ack(a: Ack, x_device_token: str = Header("", description=apidoc.TOKEN_DOC)):
    run_ref = db.collection("runs").document(a.run_id)
    ref = run_ref.collection("alerts").document(str(a.alert_n))
    snap = ref.get()
    if not snap.exists or snap.to_dict()["junction_id"] != a.junction_id:
        return err(404, "unknown_alert")
    if not tokens.disabled():  # the cop on duty at that junction, or the run's own vehicle
        run = run_ref.get().to_dict() or {}
        v = db.collection("vehicles").document(run.get("vehicle_plate") or "-").get().to_dict() or {}
        if bad := deny(x_device_token, duty_hash(a.junction_id), v.get("device_token_hash")):
            return bad
    d = snap.to_dict()
    if d.get("acked_at"):  # idempotent: the first ACK stands
        acked, latency = d["acked_at"], d.get("ack_latency_s")
    else:
        acked = datetime.now(UTC)
        latency = round(max((acked - d["created_at"]).total_seconds(), 0), 1) if d.get("created_at") else None
        ref.update({"acked_at": acked, "ack_latency_s": latency, "acked_by": a.device_id})
        log(event="ack", run_id=a.run_id, junction_id=a.junction_id, alert_n=a.alert_n, ack_latency_s=latency)
    # latency_s: alias the cop page reads today
    return {"ok": True, "acked_at": acked.isoformat(), "ack_latency_s": latency, "latency_s": latency}


class Duty(BaseModel):
    model_config = ex(
        {
            "corridor": "blr",
            "junction_id": "blr_j3",
            "device_id": "dev-cop-1",
            "on": True,
            "name": "Constable Rao",
        },
    )
    corridor: str = Field(
        json_schema_extra={"enum": sorted(CORRIDORS)}
    )  # anything else is 400 unknown_corridor
    junction_id: str  # "blr_j3" or "j3"
    device_id: str
    on: StrictBool
    name: str | None = None
    fcm_token: str | None = Field(None, max_length=4096)  # web push token of the cop's browser; see push.py


def junction_key(corridor: str, junction_id: str) -> str | JSONResponse:
    """`blr_j3` for ("blr", "j3" or "blr_j3"), else the 400/404 response."""
    c = CORRIDORS.get(corridor)
    if c is None:
        return err(400, "unknown_corridor", corridor)
    jid = junction_id.removeprefix(corridor + "_")
    if jid not in {j["id"] for j in c["junctions"]}:
        return err(404, "unknown_junction", junction_id)
    return f"{corridor}_{jid}"


@app.post("/duty", **meta("corridor", "A junction cop goes on or off duty", DutyOut, 400, 401, 403, 404, 422))
def duty(d: Duty, x_device_token: str = Header("", description=apidoc.TOKEN_DOC)):
    key = junction_key(d.corridor, d.junction_id)
    if isinstance(key, JSONResponse):
        return key
    since = datetime.now(UTC)
    doc = {"device_id": d.device_id, "name": d.name, "on": d.on, "since": since}
    ref = db.collection("duty").document(key)
    extra: dict[str, Any] = {}
    if d.on:  # going on duty rotates the junction's token: the previous cop's calls then get 403
        token, h = tokens.mint()
        # merge keeps note_count; the previous cop's push token goes unless this device sent its own
        ref.set({**doc, "device_token_hash": h, "fcm_token": d.fcm_token or DELETE_FIELD}, merge=True)
        extra["device_token"] = token
    else:
        if bad := deny(x_device_token, duty_hash(key)):
            return bad
        ref.set({**doc, "device_token_hash": DELETE_FIELD, "fcm_token": DELETE_FIELD}, merge=True)
    log(event="duty", junction_id=key, device_id=d.device_id, on=d.on)
    return {**doc, "since": since.isoformat(), **extra}


class CopNoteReq(BaseModel):
    model_config = ex(
        {"corridor": "blr", "junction_id": "blr_j3", "text": "bus stalled, need two more minutes"},
        anyOf=[  # 400 bad_request otherwise
            {"required": ["audio_b64"], "properties": {"audio_b64": {"type": "string", "minLength": 1}}},
            {"required": ["text"], "properties": {"text": {"type": "string", "minLength": 1}}},
        ],
    )
    corridor: str = Field(json_schema_extra={"enum": sorted(CORRIDORS)})
    junction_id: str
    audio_b64: str | None = None
    mime: str | None = None
    text: str | None = None


@app.post(
    "/cop-note",
    **meta("corridor", "The cop's spoken or typed report to control", CopNoteOut, 400, 401, 403, 404, 422),
)
def cop_note(
    n: CopNoteReq, bg: BackgroundTasks, x_device_token: str = Header("", description=apidoc.TOKEN_DOC)
):
    """The on-duty cop's spoken or typed report. Gemini only fills the {kind, extra_seconds, reason} schema; what happens
    next is copnote.apply, plain rules (a cannot_clear or a delay over 90 s then hands the junction to the re-planner agent in
    the background)."""
    key = junction_key(n.corridor, n.junction_id)
    if isinstance(key, JSONResponse):
        return key
    if bad := deny(x_device_token, duty_hash(key)):
        return bad
    try:
        audio = base64.b64decode(n.audio_b64, validate=True) if n.audio_b64 else None
    except ValueError:
        return err(400, "bad_request", "audio_b64 is not valid base64")
    if not (audio or n.text):
        return err(400, "bad_request", "audio_b64 or text required")
    try:
        note = gemini.cop_note(audio, n.mime, n.text)
    except ExtractionFailed:
        log(event="cop_note_extraction_failed", junction_id=key)
        return err(422, "extraction_failed", fallback="text")
    return copnote.apply(db, key, note, datetime.now(UTC), bg)


class HospitalDuty(BaseModel):
    model_config = ex(
        {"hospital_id": "jayadeva"},
    )
    hospital_id: str


@app.post("/hospital/duty", **meta("hospital", "A hospital desk signs in", HospitalDutyOut, 400, 404, 422))
def hospital_duty(d: HospitalDuty):
    """A hospital desk signs in: hands out a token that may regenerate briefs and after-action reports. Rotates on each sign-in."""
    if not by_id(d.hospital_id):
        return err(404, "unknown_hospital")
    token, h = tokens.mint()
    db.collection("hospital_duty").document(d.hospital_id).set(
        {"device_token_hash": h, "since": datetime.now(UTC)}
    )
    return {"hospital_id": d.hospital_id, "hospital_token": token}
