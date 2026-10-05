"""Gemini on Vertex. Extracts fields only; never scores severity. No tools."""
import json
import os
from typing import Literal, Optional

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

TIMEOUT_MS, LONG_TIMEOUT_MS = 8000, 15000  # audio and the brief are slower to process, so they get a longer attempt
SYSTEM = ("You transcribe emergency crew reports into fields. Extract only what was said; never infer "
          "severity or fill in values that were not stated (use null). Translate the transcript to English. "
          "Reply as JSON matching the schema.")
IMAGE_SYSTEM = (" The input is a photo of a patient monitor or ECG strip. Read only values visible on the screen; use null for "
                "anything not legible; never infer a diagnosis. transcript_en is one line describing what the monitor shows, "
                "e.g. \"Monitor: HR 112, SpO2 89%, NIBP 86/54\".")
LOG_SYSTEM = (" List each drug, procedure or observation the crew says was done or given in interventions, with dose, "
              "route and time exactly as spoken; leave a part null if it was not said. Never infer an intervention.")


NO_THINKING = types.ThinkingConfig(thinking_budget=0)  # extraction and the brief restate input; thinking only adds latency


class ExtractionFailed(Exception):
    pass


class Vitals(BaseModel):
    sbp: Optional[int] = None
    dbp: Optional[int] = None
    hr: Optional[int] = None
    spo2: Optional[int] = None
    rr: Optional[int] = None
    temp: Optional[float] = None


class Intervention(BaseModel):
    kind: Literal["drug", "procedure", "observation"]
    name: str
    dose: Optional[str] = None
    route: Optional[str] = None
    time_note: Optional[str] = None


class Extraction(BaseModel):
    age: Optional[int] = None
    sex: Optional[str] = None
    complaint: Optional[str] = None
    conscious: Optional[bool] = None
    breathing: Optional[bool] = None
    vitals: Vitals = Vitals()
    trapped_persons: Optional[int] = None
    incident_type: Optional[str] = None
    transcript_en: str


class LogExtraction(Extraction):
    interventions: list[Intervention] = []


def log(**kw):
    print(json.dumps(kw), flush=True)


def _client(timeout_ms=TIMEOUT_MS):
    return genai.Client(vertexai=True, project=os.environ.get("GCP_PROJECT", "green-corridor-2026"),
                        location=os.environ.get("GEMINI_LOCATION", "global"),
                        http_options=types.HttpOptions(timeout=timeout_ms))


def generate_json(models, contents, cfg, schema, run_id=None, timeout_ms=TIMEOUT_MS, what="extract"):
    """Try each model in order; returns (reply, model) for the first reply that validates against `schema`. ponytail: no backoff."""
    client = _client(timeout_ms)
    for model in models:
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=cfg)
            out = schema.model_validate_json(resp.text or "").model_dump()
            log(event=f"{what}_ok", run_id=run_id, model=model)
            return out, model
        except (ValidationError, errors.APIError, httpx.TimeoutException) as e:  # bad JSON/schema, refusal, timeout, quota
            log(event=f"{what}_retry", run_id=run_id, model=model, error=type(e).__name__, detail=str(e)[:200])
    raise ExtractionFailed(run_id)


def text_models():
    """Brief and rationale: the richer model first, the extraction model as fallback."""
    return [os.environ.get("GEMINI_TEXT_MODEL", "gemini-3-flash-preview"), os.environ["GEMINI_MODEL"]]


def extract(audio_bytes, mime, text, vehicle_type, lang_hint, run_id=None, interventions=False, image_bytes=None) -> dict:
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
        system_instruction=SYSTEM + (IMAGE_SYSTEM if image_bytes else "") + (LOG_SYSTEM if interventions else "") + ctx,
        response_mime_type="application/json", response_schema=schema, thinking_config=NO_THINKING)
    # ponytail: first model twice, then the fallback once
    return generate_json([os.environ["GEMINI_MODEL"]] * 2 + [os.environ["GEMINI_FALLBACK_MODEL"]], parts, cfg, schema, run_id,
                         LONG_TIMEOUT_MS if audio_bytes or image_bytes else TIMEOUT_MS)[0]


def explain_sequence(seq: list, lang: str) -> str:
    client = _client()  # keep a reference: a temporary Client closes its HTTP session on garbage collection
    prompt = (f"Vehicle order at a junction (decided by rules): {json.dumps(seq)}. "
              f"In one short plain-text sentence in language code '{lang}', say who goes first and why.")
    models = text_models()
    for model in models:
        try:
            return (client.models.generate_content(model=model, contents=prompt).text or "").strip()
        except (errors.APIError, httpx.TimeoutException):
            if model == models[-1]:
                raise
