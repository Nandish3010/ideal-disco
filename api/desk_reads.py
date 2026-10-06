"""Token-gated reads of the clinical documents that firestore.rules.production denies to browsers. Work in demo mode too."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

import production
from firestore_client import db

router = APIRouter()


def iso(v: Any) -> Any:
    """Firestore timestamps (and any nested ones) as ISO strings, so the body is plain JSON."""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: iso(x) for k, x in v.items()}
    if isinstance(v, list):
        return [iso(x) for x in v]
    return v


def not_found(code: str) -> JSONResponse:
    return production.refuse(404, code)


@router.get("/runs/{run_id}/log")
def run_log(run_id: str, x_device_token: str = Header("")):
    """The transit log, oldest first: [{n, t, kind, transcript_en, fields, interventions, confirmed, photo_url?}]. Needs the
    run's vehicle token or a hospital desk token."""
    run_ref = db.collection("runs").document(run_id)
    if not run_ref.get().exists:
        return not_found("unknown_run")
    if bad := production.desk_problem(x_device_token, run_id):
        return bad
    docs = sorted(run_ref.collection("log").stream(), key=lambda d: int(d.id))
    return [{"n": int(d.id), **iso(d.to_dict())} for d in docs]


@router.get("/briefs/{run_id}")
def get_brief(run_id: str, x_device_token: str = Header("")):
    """The stored ATMIST brief (SCHEMA.md, briefs/{run_id}). Same tokens as the log; 404 `no_brief` until one is written."""
    if not db.collection("runs").document(run_id).get().exists:
        return not_found("unknown_run")
    if bad := production.desk_problem(x_device_token, run_id):
        return bad
    snap = db.collection("briefs").document(run_id).get()
    return iso(snap.to_dict()) if snap.exists else not_found("no_brief")
