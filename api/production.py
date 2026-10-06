"""PRODUCTION_MODE=1: the public-write demo conveniences are refused and clinical reads go through the API.

The demo leaves POST /incidents, POST /vehicles/bind and POST /hospital/duty open so a judge can use every screen. With
PRODUCTION_MODE=1 they need a credential an agency holds, and the reads that firestore.rules.production denies (the
run log, the brief, the after-action report) need a vehicle or hospital desk token:

| call | header |
|---|---|
| POST /incidents | X-Dispatch-Token == env DISPATCH_TOKEN |
| POST /vehicles/bind, POST /hospital/duty | X-Agency-Key == env AGENCY_KEY |
| POST /brief | a hospital desk token (X-Device-Token) |
| POST /runs/{id}/after-action | the run's vehicle token or a hospital desk token |
| GET /runs/{id}/log, GET /briefs/{id} | the same (desk_reads.py) |

A credential env that is unset refuses every call: production never falls open. DEVICE_TOKENS_DISABLED is ignored."""

import hmac
import os
import re

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import tokens
from firestore_client import db

AGENCY_PATHS = {"/vehicles/bind", "/hospital/duty"}
AFTER_ACTION = re.compile(r"/runs/([^/]+)/after-action")


def enabled() -> bool:
    return os.environ.get("PRODUCTION_MODE") == "1"


def refuse(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": code, "detail": code.replace("_", " ")}, status_code=status)


def secret_problem(given: str, env: str, missing_code: str) -> JSONResponse | None:
    """401 when the header is absent, 403 when it is wrong or the env is unset."""
    want = os.environ.get(env, "")
    if not want:
        return refuse(403, "forbidden")
    if not given:
        return refuse(401, missing_code)
    return None if hmac.compare_digest(given.encode(), want.encode()) else refuse(403, "forbidden")


def desk_hashes() -> list[str | None]:
    return [d.to_dict().get("device_token_hash") for d in db.collection("hospital_duty").stream()]


def desk_problem(token: str, run_id: str | None = None) -> JSONResponse | None:
    """None when `token` is a hospital desk token or, for a run, that run's vehicle token; else the 401/403."""
    hashes = desk_hashes()
    if run_id:
        run = db.collection("runs").document(run_id).get().to_dict() or {}
        vehicle = db.collection("vehicles").document(run.get("vehicle_plate") or "-").get().to_dict() or {}
        hashes.append(vehicle.get("device_token_hash"))
    p = tokens.problem(token, hashes)
    return refuse(*p) if p else None


def check(request: Request) -> JSONResponse | None:
    """The refusal for a demo-only call made in production mode, else None."""
    path, h = request.url.path, request.headers
    if request.method != "POST":
        return None
    if path == "/incidents":
        return secret_problem(h.get("X-Dispatch-Token", ""), "DISPATCH_TOKEN", "dispatch_token_required")
    if path in AGENCY_PATHS:
        return secret_problem(h.get("X-Agency-Key", ""), "AGENCY_KEY", "agency_key_required")
    if path == "/brief":
        return desk_problem(h.get("X-Device-Token", ""))
    if m := AFTER_ACTION.fullmatch(path):
        return desk_problem(h.get("X-Device-Token", ""), m.group(1))
    return None


async def guard(request: Request, call_next):
    """HTTP middleware: a no-op unless PRODUCTION_MODE=1."""
    if enabled() and (bad := await run_in_threadpool(check, request)):
        return bad
    return await call_next(request)
