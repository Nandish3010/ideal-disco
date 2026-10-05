"""Hospital handover brief: ATMIST + prep checklist from the transit log. Transcription support; Gemini only restates the log."""
import json
import os

from google.genai import types
from pydantic import BaseModel, Field

from gemini import LONG_TIMEOUT_MS, NO_THINKING, generate_json, offline, text_models

DISCLAIMER = "Synthetic patient. Clinician confirms."
SYSTEM = ("You help clinicians by turning an ambulance crew's transit log into a handover brief; this is transcription "
          "support, not a diagnosis. Use only values that appear in the log or run record and never invent one; a "
          "missing value is \"unknown\" and anything the log leaves uncertain or that only one note suggests is marked "
          "\"unconfirmed\". Fill the ATMIST fields: age (with sex if stated), time of onset or incident (only if stated), "
          "mechanism or presenting complaint, injuries or findings, signs (the latest vitals, each with its unit) and "
          "treatment (every intervention so far, with dose, route and time as logged). The checklist has 3 to 8 short "
          "imperative preparation steps for the receiving team that suit the suspected condition (for chest pain with ST "
          "features, for example: Activate cath lab, Prepare heparin, Page cardiology); if the condition is unclear keep "
          "to generic steps. The summary is one paragraph. Reply as JSON matching the schema.")


class Atmist(BaseModel):
    age: str
    time: str
    mechanism: str
    injuries: str
    signs: str
    treatment: str


class Brief(BaseModel):
    atmist: Atmist
    checklist: list[str] = Field(min_length=3, max_length=8)
    summary: str


OFFLINE_BRIEF = {"atmist": {k: "offline" for k in Atmist.model_fields}, "checklist": ["Offline stub", "Offline stub", "Offline stub"],
                 "summary": "Offline stub brief."}


def generate(run, log_entries, lang="en", run_id=None):
    """Returns ({atmist, checklist, summary}, model). Raises gemini.ExtractionFailed when no model gives a valid brief."""
    if offline():
        return OFFLINE_BRIEF, "offline"
    keep = ("vehicle_type", "acuity_tier", "confirmed_tier", "destination", "eta_hospital_s")
    ctx = {"run": {k: run.get(k) for k in keep}, "log": log_entries}
    cfg = types.GenerateContentConfig(system_instruction=SYSTEM + f" Write in language code '{lang}'.",
                                      response_mime_type="application/json", response_schema=Brief,
                                      thinking_config=NO_THINKING)
    # ponytail: one try per model, 15 s each, since this runs inline in /location (the preview text model often takes > 8 s)
    return generate_json(text_models(), json.dumps(ctx, default=str),
                         cfg, Brief, run_id, LONG_TIMEOUT_MS, what="brief")


if __name__ == "__main__":
    Brief.model_validate({"atmist": {k: "x" for k in Atmist.model_fields}, "checklist": ["a", "b", "c"], "summary": "s"})
    for bad in (["a", "b"], ["a"] * 9):
        try:
            Brief.model_validate({"atmist": {k: "x" for k in Atmist.model_fields}, "checklist": bad, "summary": "s"})
        except ValueError:
            continue
        raise AssertionError("checklist length not enforced")
    os.environ["OFFLINE_AI"] = "1"
    out, model = generate({}, [])
    Brief.model_validate(out)
    assert model == "offline"
    print("brief ok")
