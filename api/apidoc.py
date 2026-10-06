"""OpenAPI documentation for the API: tags, the shared error envelope, and response models with examples. Documentation
only: the endpoints still return plain dicts, these models are never used to filter or validate a response (the
contract tests in api/tests compare real responses against them)."""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, ConfigDict


def ex(*examples: dict, **schema: Any) -> ConfigDict:
    """Model config carrying OpenAPI examples, plus any JSON Schema keywords the field types cannot express."""
    return ConfigDict(json_schema_extra={"examples": list(examples), **schema})


TAGS = [
    {
        "name": "dispatch",
        "description": "Mock registry and dispatch console: bind a device to a vehicle, open an incident.",
    },
    {
        "name": "runs",
        "description": "A vehicle's run from start to end: confirmation, report cards and after-action reports.",
    },
    {
        "name": "triage",
        "description": "Crew-side patient data: extraction from voice, text or a monitor photo, the log and the hospital brief.",
    },
    {
        "name": "corridor",
        "description": "The live corridor: location ticks, alert acknowledgements and the junction cop's duty and notes.",
    },
    {"name": "hospital", "description": "Hospital desk sign-in and the destination routing agent."},
    {"name": "ops", "description": "Health and scheduled housekeeping."},
]

DESCRIPTION = """Preempts traffic signals along an emergency vehicle's route: ticks in, alerts out.

**Errors.** Every 4xx and 5xx body is the same envelope, `{"error": "<code>", "detail": "<text>"}`, sometimes with extra keys
(`state`, `fallback`, `retry_after_s`). Every response carries `X-Request-Id`.

**Device tokens.** Calls that change a run need `X-Device-Token` (handed out by `/vehicles/bind`, `/duty` and
`/hospital/duty`): 401 without it, 403 with the wrong one.

**Rate limits.** Per IP in one-minute windows shared by every instance: 10 heavy calls (`/triage`, `/log`, `/brief`, `/route`,
`/cop-note`, `/runs/{run_id}/after-action`), 900 `/location`, 60 everything else. Over the limit: 429 `rate_limited` with
`Retry-After`.

**Idempotency.** `POST /location` takes an optional `Idempotency-Key` header (or `tick_id` in the body): a repeat within
10 minutes returns the stored response, with `Idempotent-Replayed: true`, and changes nothing."""

ERRORS = {
    400: "Bad request: a missing or malformed input the schema cannot express.",
    401: "A device token is required (`device_token_required`).",
    403: "Not allowed (`device_token_mismatch`, `unregistered_vehicle`, `run_not_active`, `forbidden`).",
    404: "Not found (`unknown_run`, `unknown_alert`, `unknown_junction`, `not_found`).",
    405: "Method not allowed.",
    409: "The run is not in a state that allows this (`run_not_finished`, `not_routable`).",
    422: "Validation failed (`validation_error`) or the extraction could not read the input (`extraction_failed`).",
    429: "Rate limited (`rate_limited`) or a per-run cap (`run_cap_reached`, `brief_cooldown`).",
    500: "Unexpected error (`internal_error`).",
    502: "The model call failed (`brief_failed`, `after_action_failed`).",
    503: "Firestore is unavailable (`store_unavailable`).",
}


class ErrorEnvelope(BaseModel):
    """The one error body. Some errors add keys: `state`, `fallback`, `retry_after_s`."""

    error: str
    detail: str
    model_config = ex({"error": "unknown_run", "detail": "unknown run"})


def errs(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {c: {"model": ErrorEnvelope, "description": ERRORS[c]} for c in codes}


def meta(
    tag: str, summary: str, ok: type[BaseModel], *codes: int, headers: dict | None = None
) -> dict[str, Any]:
    """Route keyword arguments: tag, summary, the 200 model and the error codes this route can answer beyond the shared
    429 / 500 / 503."""
    return {
        "tags": [tag],
        "summary": summary,
        "responses": {
            200: {"model": ok, "description": "OK", **({"headers": headers} if headers else {})},
            **errs(*codes),
        },
    }


class Health(BaseModel):
    ok: bool
    model: str | None = None
    model_config = ex({"ok": True, "model": "gemini-3.1-flash-lite"})


class Bound(BaseModel):
    plate: str
    type: str
    agency: str | None = None
    active: bool
    bound_device_id: str
    device_token: str
    model_config = ex(
        {
            "plate": "KA01AB1234",
            "type": "ambulance",
            "agency": "108 Karnataka",
            "active": True,
            "bound_device_id": "dev-1",
            "device_token": "kQ3x0m2Yw9n7fVqJ1uZ4hT6sB8cD5eAaLpOiRgNzXyU",
        }
    )


class IncidentOut(BaseModel):
    incident_id: str
    model_config = ex({"incident_id": "INC-4BC6E7"})


class RunOut(BaseModel):
    """`start`: just `run_id`. `end`: also `state` and the report card (null when the corridor is unknown)."""

    run_id: str
    state: str | None = None
    report: dict | None = None
    model_config = ex(
        {"run_id": "run-1a2b3c4d"},
        {"run_id": "run-1a2b3c4d", "state": "ended", "report": {"minutes_saved": 4.2}},
    )


class TriageOut(BaseModel):
    fields: dict
    transcript_en: str
    suggested_tier: str
    photo_url: str | None = None
    model_config = ex(
        {
            "fields": {"complaint": "chest pain", "conscious": True, "vitals": {"sbp": 85, "dbp": 50}},
            "transcript_en": "Patient has chest pain, blood pressure 85 over 50",
            "suggested_tier": "critical",
        }
    )


class LogOut(BaseModel):
    n: int
    transcript_en: str
    fields: dict
    interventions: list[dict]
    confirmed: bool
    photo_url: str | None = None
    model_config = ex(
        {
            "n": 3,
            "transcript_en": "Oxygen 4 litres started",
            "fields": {"transcript_en": "Oxygen 4 litres started"},
            "interventions": [
                {"kind": "drug", "name": "oxygen", "dose": "4 litres", "route": None, "time_note": None}
            ],
            "confirmed": False,
        }
    )


class ConfirmOut(BaseModel):
    run_id: str
    confirmed_tier: str
    patient_on_board: bool
    routing: dict | None = None
    model_config = ex(
        {"run_id": "run-amb-1", "confirmed_tier": "critical", "patient_on_board": True, "routing": None}
    )


class RoutingOut(BaseModel):
    """The `runs.routing` object the hospital routing agent writes."""

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [{"hospital_id": "jayadeva", "reason": "Cardiac cath lab, 9 min", "fallback": False}]
        },
    )


class BriefOut(BaseModel):
    atmist: dict
    checklist: list[str]
    summary: str
    disclaimer: str
    generated_at: str | None = None
    model: str | None = None
    model_config = ex(
        {
            "atmist": {"age": "58", "time": "09:02", "mechanism": "unknown", "injuries": "unknown"},
            "checklist": ["Cath lab on standby", "ECG on arrival"],
            "summary": "58 year old male, chest pain, BP 85/50.",
            "disclaimer": "Synthetic patient. Clinician confirms.",
            "generated_at": "2026-10-05T09:03:00Z",
            "model": "gemini-3-flash-preview",
        }
    )


class AfterActionOut(BaseModel):
    summary: str
    timeline: list[dict]
    issues: list[str]
    recommendations: list[str]
    generated_at: str | None = None
    model: str | None = None
    model_config = ex(
        {
            "summary": "Ambulance reached the hospital 4 minutes early; all five alerts were acknowledged.",
            "timeline": [{"offset": "t+0:00", "t": "2026-10-05T09:00:00Z", "event": "Run started"}],
            "issues": [],
            "recommendations": ["Keep the cop at J3 on the radio roster."],
            "generated_at": "2026-10-05T09:12:00Z",
            "model": "gemini-3-flash-preview",
        }
    )


class Fired(BaseModel):
    junction: str
    stage: str


class LocationOut(BaseModel):
    state: str
    next_junction: str | None
    approach: str | None
    jam_m: float | None
    eta_s: float | None
    stage: str | None
    exit_move: str | None
    eta_hospital_s: float | None
    alerts_fired: list[Fired]
    brief_due: bool
    observed_speed_60s: float
    traffic: str | None
    model_config = ex(
        {
            "state": "en_route",
            "next_junction": "blr_j3",
            "approach": "NE",
            "jam_m": 520,
            "eta_s": 143,
            "stage": "PREPARE",
            "exit_move": "left",
            "eta_hospital_s": 412,
            "alerts_fired": [{"junction": "blr_j3", "stage": "PREPARE"}],
            "brief_due": False,
            "observed_speed_60s": 13.2,
            "traffic": "live",
        }
    )


class AckOut(BaseModel):
    ok: bool
    acked_at: str
    ack_latency_s: float | None
    latency_s: float | None
    model_config = ex(
        {"ok": True, "acked_at": "2026-10-05T09:03:26Z", "ack_latency_s": 6.2, "latency_s": 6.2}
    )


class HousekeepingOut(BaseModel):
    stale: int
    escalated: int
    runs_checked: int
    model_config = ex({"stale": 1, "escalated": 2, "runs_checked": 5})


class DutyOut(BaseModel):
    device_id: str
    name: str | None
    on: bool
    since: str
    device_token: str | None = None
    model_config = ex(
        {
            "device_id": "dev-cop-1",
            "name": "Constable Rao",
            "on": True,
            "since": "2026-10-05T09:00:00Z",
            "device_token": "kQ3x0m2Yw9n7fVqJ1uZ4hT6sB8cD5eAaLpOiRgNzXyU",
        }
    )


class CopNoteOut(BaseModel):
    n: int
    kind: str
    extra_seconds: int | None = None
    reason: str | None = None
    transcript_en: str | None = None
    effects: dict
    action_text: str
    model_config = ex(
        {
            "n": 0,
            "kind": "delay",
            "extra_seconds": 120,
            "reason": "bus stalled",
            "transcript_en": "Bus stalled, need two more minutes",
            "effects": {"phase_extended_s": 120, "acked": 0, "escalated": 1, "blocked_s": 0},
            "action_text": "Green extended by 2 min, escalated",
        }
    )


class HospitalDutyOut(BaseModel):
    hospital_id: str
    hospital_token: str
    model_config = ex(
        {"hospital_id": "jayadeva", "hospital_token": "kQ3x0m2Yw9n7fVqJ1uZ4hT6sB8cD5eAaLpOiRgNzXyU"}
    )


TOKEN_DOC = (
    "Device token from /vehicles/bind (vehicle), /duty (junction cop) or /hospital/duty (hospital desk)."
)


def install_openapi(app: FastAPI) -> None:
    """Replace app.openapi: the generated schema plus one shared `Error` response (the envelope, with X-Request-Id) that
    every operation answers for 429, 500 and 503, and that `ErrorEnvelope` is the schema of."""

    def build() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
        )
        shared = {
            "description": "The error envelope.",
            "headers": {
                "X-Request-Id": {
                    "description": "Echo of the caller's id, else a new uuid4.",
                    "schema": {"type": "string"},
                }
            },
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
        }
        schema.setdefault("components", {}).setdefault("responses", {})["Error"] = shared
        for unused in (
            "HTTPValidationError",
            "ValidationError",
        ):  # 422 is the envelope here, FastAPI's default is not
            schema["components"]["schemas"].pop(unused, None)
        for item in schema["paths"].values():
            for op in item.values():
                for code in ("429", "500", "503"):
                    op["responses"].setdefault(code, {"$ref": "#/components/responses/Error"})
        app.openapi_schema = schema
        return schema

    app.openapi = build  # type: ignore[method-assign]
