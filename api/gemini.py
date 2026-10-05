"""Gemini on Vertex. Extracts fields only; never scores severity. No tools."""
import json
import os
from typing import Optional

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

TIMEOUT_MS = 8000
SYSTEM = ("You transcribe emergency crew reports into fields. Extract only what was said; never infer "
          "severity or fill in values that were not stated (use null). Translate the transcript to English. "
          "Reply as JSON matching the schema.")


class ExtractionFailed(Exception):
    pass


class Vitals(BaseModel):
    sbp: Optional[int] = None
    dbp: Optional[int] = None
    hr: Optional[int] = None
    spo2: Optional[int] = None
    rr: Optional[int] = None
    temp: Optional[float] = None


class Extraction(BaseModel):
    complaint: Optional[str] = None
    conscious: Optional[bool] = None
    breathing: Optional[bool] = None
    vitals: Vitals = Vitals()
    trapped_persons: Optional[int] = None
    incident_type: Optional[str] = None
    transcript_en: str


def log(**kw):
    print(json.dumps(kw), flush=True)


def _client():
    return genai.Client(vertexai=True, project=os.environ.get("GCP_PROJECT", "green-corridor-2026"),
                        location=os.environ.get("GEMINI_LOCATION", "global"),
                        http_options=types.HttpOptions(timeout=TIMEOUT_MS))


def extract(audio_bytes, mime, text, vehicle_type, lang_hint, run_id=None) -> dict:
    parts = []
    if audio_bytes:
        parts.append(types.Part.from_bytes(data=audio_bytes, mime_type=mime or "audio/webm"))
    if text:
        parts.append(text)
    ctx = f" Reporting vehicle: {vehicle_type}." + (f" Likely language: {lang_hint}." if lang_hint else "")
    cfg = types.GenerateContentConfig(system_instruction=SYSTEM + ctx, response_mime_type="application/json",
                                      response_schema=Extraction)
    # ponytail: primary twice, then fallback once; no backoff
    attempts = [os.environ["GEMINI_MODEL"]] * 2 + [os.environ["GEMINI_FALLBACK_MODEL"]]
    client = _client()
    for model in attempts:
        try:
            resp = client.models.generate_content(model=model, contents=parts, config=cfg)
            out = Extraction.model_validate_json(resp.text or "").model_dump()
            log(event="extract_ok", run_id=run_id, model=model)
            return out
        except (ValidationError, errors.APIError) as e:  # bad JSON/schema, refusal, timeout, quota
            log(event="extract_retry", run_id=run_id, model=model, error=type(e).__name__, detail=str(e)[:200])
    raise ExtractionFailed(run_id)


def explain_sequence(seq: list, lang: str) -> str:
    resp = _client().models.generate_content(
        model=os.environ["GEMINI_MODEL"],
        contents=f"Vehicle order at a junction (decided by rules): {json.dumps(seq)}. "
                 f"In one short plain-text sentence in language code '{lang}', say who goes first and why.")
    return (resp.text or "").strip()
