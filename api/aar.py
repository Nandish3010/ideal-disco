"""After-action report for a finished run. The timeline is built here from the stored record; Gemini only writes the narrative parts."""

import json
from datetime import datetime

from google.genai import types
from pydantic import BaseModel

from gemini import LONG_TIMEOUT_MS, NO_THINKING, generate_json, offline, text_models

DISCLAIMER = "Drafted from the recorded run data. A person reviews it before it is filed."
SYSTEM = (
    "You write an incident after-action report for the agency that ran this emergency vehicle corridor. Be "
    "factual and use only the data given; never invent a time, place, count or cause. Mark anything uncertain "
    'or missing as "unconfirmed". The summary is one paragraph on what happened and how the run ended. Issues '
    "are concrete problems visible in the data (escalated or unacknowledged alerts, slow acknowledgements, "
    "off-route or stale periods, fallback routing); an empty list is fine. Recommendations are 0 to 5 short "
    "actions that follow from those issues. The timeline is supplied separately; do not write one. Reply as JSON "
    "matching the schema."
)


class Narrative(BaseModel):
    summary: str
    issues: list[str]
    recommendations: list[str]


OFFLINE_NARRATIVE = {
    "summary": "Offline stub after-action report.",
    "issues": ["Offline stub"],
    "recommendations": ["Offline stub"],
}


def _dt(v):
    return datetime.fromisoformat(v) if isinstance(v, str) else v


def timeline(run, log_entries, alerts, report):
    """[{t, event}] sorted by time, from ticks, crew log entries, alerts (stage), acks, escalations and the run end."""
    ev = [(run.get("started_at"), f"Run created ({run.get('vehicle_type')} {run.get('vehicle_plate')})")]
    ev.append((run.get("first_tick_at"), "First location tick, drive started"))
    ev += [(e.get("t"), f"Crew log entry ({e.get('kind')})") for e in log_entries]
    for a in alerts:
        jid = a.get("junction_id")
        jam = f", {a['jam_m']} m queue" if a.get("jam_m") else ""
        ev.append((a.get("created_at"), f"{a.get('stage')} alert at {jid}{jam}"))
        if a.get("acked_at"):
            lat = a.get("ack_latency_s")
            ev.append(
                (
                    a["acked_at"],
                    f"Alert at {jid} acknowledged" + (f" after {lat} s" if lat is not None else ""),
                )
            )
        if a.get("escalated_at"):
            ev.append((a["escalated_at"], f"Alert at {jid} escalated with no acknowledgement"))
    ticks = run.get("ticks") or []
    end = (report or {}).get("ended_at") or (ticks[-1]["t"] if ticks else None)
    ev.append((end, f"Run {run.get('state')}"))
    return [
        {"t": _dt(t).isoformat(), "event": e}
        for t, e in sorted((x for x in ev if x[0]), key=lambda x: _dt(x[0]))
    ]


def generate(run, log_entries, alerts, report, routing, run_id=None):
    """Returns ({summary, timeline, issues, recommendations, disclaimer}, model). Raises gemini.ExtractionFailed."""
    tl = timeline(run, log_entries, alerts, report)
    if offline():
        return {**OFFLINE_NARRATIVE, "timeline": tl, "disclaimer": DISCLAIMER}, "offline"
    keep = ("vehicle_type", "confirmed_tier", "state", "ended_reason", "destination", "source", "corridor")
    ctx = {
        "run": {k: run.get(k) for k in keep},
        "report": report,
        "routing": {k: v for k, v in (routing or {}).items() if k != "trace"},
        "alerts": [
            {k: a.get(k) for k in ("junction_id", "stage", "jam_m", "eta_s", "ack_latency_s", "escalated")}
            for a in alerts
        ],
        "log_entries": len(log_entries),
        "timeline": tl,
    }
    cfg = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        response_mime_type="application/json",
        response_schema=Narrative,
        thinking_config=NO_THINKING,
    )
    out, model = generate_json(
        text_models(), json.dumps(ctx, default=str), cfg, Narrative, run_id, LONG_TIMEOUT_MS, what="aar"
    )
    return {**out, "timeline": tl, "disclaimer": DISCLAIMER}, model
