"""Gemini on Vertex. Extracts fields only; never scores severity. No tools."""

import json
import os
from typing import Literal

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from logctx import log

TIMEOUT_MS, LONG_TIMEOUT_MS = (
    8000,
    15000,
)  # audio and the brief are slower to process, so they get a longer attempt
SYSTEM = (
    "You transcribe emergency crew reports into fields. Extract only what was said; never infer "
    "severity or fill in values that were not stated (use null). Translate the transcript to English. "
    "Reply as JSON matching the schema."
)
IMAGE_SYSTEM = (
    " The input is a photo of a patient monitor or ECG strip. Read only values visible on the screen; use null for "
    "anything not legible; never infer a diagnosis. transcript_en is one line describing what the monitor shows, "
    'e.g. "Monitor: HR 112, SpO2 89%, NIBP 86/54".'
)
LOG_SYSTEM = (
    " List each drug, procedure or observation the crew says was done or given in interventions, with dose, "
    "route and time exactly as spoken; leave a part null if it was not said. Never infer an intervention."
)


NO_THINKING = types.ThinkingConfig(
    thinking_budget=0
)  # extraction and the brief restate input; thinking only adds latency


class ExtractionFailed(Exception):
    pass


def offline() -> bool:
    """OFFLINE_AI=1 (dev only): no Gemini, Translation, TTS, Storage or ADK calls anywhere in the API."""
    return os.environ.get("OFFLINE_AI") == "1"


class Vitals(BaseModel):
    sbp: int | None = None
    dbp: int | None = None
    hr: int | None = None
    spo2: int | None = None
    rr: int | None = None
    temp: float | None = None


class Intervention(BaseModel):
    kind: Literal["drug", "procedure", "observation"]
    name: str
    dose: str | None = None
    route: str | None = None
    time_note: str | None = None


class Extraction(BaseModel):
    age: int | None = None
    sex: str | None = None
    complaint: str | None = None
    conscious: bool | None = None
    breathing: bool | None = None
    vitals: Vitals = Vitals()
    trapped_persons: int | None = None
    incident_type: str | None = None
    transcript_en: str


class LogExtraction(Extraction):
    interventions: list[Intervention] = []


def _client(timeout_ms=TIMEOUT_MS):
    return genai.Client(
        vertexai=True,
        project=os.environ.get("GCP_PROJECT", "green-corridor-2026"),
        location=os.environ.get("GEMINI_LOCATION", "global"),
        http_options=types.HttpOptions(timeout=timeout_ms),
    )


def generate_json(models, contents, cfg, schema, run_id=None, timeout_ms=TIMEOUT_MS, what="extract"):
    """Try each model in order; returns (reply, model) for the first reply that validates against `schema`. ponytail: no backoff."""
    client = _client(timeout_ms)
    for model in models:
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=cfg)
            out = schema.model_validate_json(resp.text or "").model_dump()
            log(event=f"{what}_ok", run_id=run_id, model=model)
            return out, model
        except (
            ValidationError,
            errors.APIError,
            httpx.TimeoutException,
        ) as e:  # bad JSON/schema, refusal, timeout, quota
            log(
                event=f"{what}_retry", run_id=run_id, model=model, error=type(e).__name__, detail=str(e)[:200]
            )
    raise ExtractionFailed(run_id)


def text_models():
    """Brief and rationale: the richer model first, the extraction model as fallback."""
    return [os.environ.get("GEMINI_TEXT_MODEL", "gemini-3-flash-preview"), os.environ["GEMINI_MODEL"]]


def extract(
    audio_bytes, mime, text, vehicle_type, lang_hint, run_id=None, interventions=False, image_bytes=None
) -> dict:
    if offline():
        raise ExtractionFailed(run_id)
    parts = []
    if audio_bytes:
        parts.append(types.Part.from_bytes(data=audio_bytes, mime_type=mime or "audio/webm"))
    if image_bytes:
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime))
    if text:
        parts.append(text)
    ctx = f" Reporting vehicle: {vehicle_type}." + (f" Likely language: {lang_hint}." if lang_hint else "")
    schema = LogExtraction if interventions else Extraction
    cfg = types.GenerateContentConfig(
        system_instruction=SYSTEM
        + (IMAGE_SYSTEM if image_bytes else "")
        + (LOG_SYSTEM if interventions else "")
        + ctx,
        response_mime_type="application/json",
        response_schema=schema,
        thinking_config=NO_THINKING,
    )
    # ponytail: first model twice, then the fallback once
    return generate_json(
        [os.environ["GEMINI_MODEL"]] * 2 + [os.environ["GEMINI_FALLBACK_MODEL"]],
        parts,
        cfg,
        schema,
        run_id,
        LONG_TIMEOUT_MS if audio_bytes or image_bytes else TIMEOUT_MS,
    )[0]


def explain_sequence(facts: list, lang: str) -> str:
    """facts: priority.rationale_facts. The model only narrates the reason codes, never the raw offsets."""
    client = _client()  # keep a reference: a temporary Client closes its HTTP session on garbage collection
    prompt = (
        f"Vehicles in the order a junction will serve them, decided by rules: {json.dumps(facts)}. "
        "offset_s is a gap the rules assigned, not an arrival order. Each reason_code says why that vehicle sits where it does "
        "against its neighbour: higher_tier = its priority tier beats the other's (tier beats ETA); earlier_eta_same_tier = equal "
        "tiers, the earlier ETA goes first; platoon_shared_approach = same approach, they share one green. Explain the ORDER using "
        "only these reason codes. Never claim that arrival order or timing caused the priority. Name the first vehicle's type. "
        "Use no numbers other than those given. "
        f"Answer in one short plain-text sentence in language code '{lang}'."
    )
    models = text_models()
    for model in models:
        try:
            return (client.models.generate_content(model=model, contents=prompt).text or "").strip()
        except (errors.APIError, httpx.TimeoutException):
            if model == models[-1]:
                raise
    raise ExtractionFailed("no text models")
