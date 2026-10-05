"""After-action report for a finished run. The timeline is built here from the stored record; Gemini only writes the narrative parts."""

import json
from datetime import datetime, timedelta

from google.genai import types
from pydantic import BaseModel

from gemini import LONG_TIMEOUT_MS, NO_THINKING, generate_json, offline, text_models

DISCLAIMER = "Drafted from the recorded run data. A person reviews it before it is filed."
SYSTEM = (
    "You write an incident after-action report for the agency that ran this emergency vehicle corridor. Be "
    "factual and use only the data given; never invent a time, place, count or cause. Mark anything uncertain "
    'or missing as "unconfirmed". The only facts you may use are these fields of the JSON input: run (vehicle_type, '
    "confirmed_tier, state, ended_reason, destination, source, corridor), report, routing, alerts (junction_id, stage, "
    "jam_m, eta_s, ack_latency_s, escalated), log_entries (a count) and timeline (events at t+minutes:seconds from run "
    "start). The summary is one paragraph on what happened and how the run ended. Issues are concrete problems visible "
    "in those facts (escalated or unacknowledged alerts, slow acknowledgements, off-route or stale periods, fallback "
    "routing); an empty list is fine. Recommendations are 0 to 5 short process actions (who does what differently next "
    "time, for example acknowledging alerts sooner or briefing the junction constable earlier) that follow directly from "
    "an issue you listed. Do not speculate about causes: never name connectivity, network, hardware or device faults, or "
    "any reason that is not written in the input. The timeline is supplied separately; do not write one. Reply as JSON "
    "matching the schema."
)
# words that point at a cause nobody recorded: an issue or recommendation using one is dropped unless the timeline says it
DENY = ("connectivity", "network", "hardware", "gps fault")


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


def offset(s: float) -> str:
    s = max(int(s), 0)
    return f"t+{s // 60}:{s % 60:02d}"


def timeline(run, log_entries, alerts, report):
    """[{t, offset, event}] in time order, from the run's own start. Every event is placed as seconds after `started_at`
    (the server clock that stamps log entries and alerts); the two client-clock times (`first_tick_at`, the last tick) are
    moved onto it using the last tick's server arrival `last_tick_at`, so a skewed or simulated tick clock cannot reorder
    the run. `t` is started_at + offset (ISO 8601), `offset` the label "t+7:25"."""
    ticks = run.get("ticks") or []
    last_at = run.get("last_tick_at")
    skew = _dt(last_at) - _dt(ticks[-1]["t"]) if last_at and ticks else None
    on_server = (lambda v: _dt(v) + skew) if skew is not None else _dt
    ev = [(run.get("started_at"), f"Run created ({run.get('vehicle_type')} {run.get('vehicle_plate')})")]
    if run.get("first_tick_at"):
        ev.append((on_server(run["first_tick_at"]), "First location tick, drive started"))
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
    end = last_at or (report or {}).get("ended_at") or (ticks[-1]["t"] if ticks else None)
    ev.append((end, f"Run {run.get('state')}"))
    ev = sorted(((_dt(t), e) for t, e in ev if t), key=lambda x: x[0])
    t0 = _dt(run["started_at"]) if run.get("started_at") else ev[0][0] if ev else None
    return [
        {
            "t": (t0 + (d := max(t - t0, timedelta(0)))).isoformat(),
            "offset": offset(d.total_seconds()),
            "event": e,
        }
        for t, e in ev
    ]


def grounded(items: list[str], tl: list[dict]) -> list[str]:
    """Drops an issue or recommendation that names a cause from DENY unless a timeline event does too."""
    seen = " ".join(e["event"] for e in tl).lower()
    return [x for x in items if all(w not in x.lower() or w in seen for w in DENY)]


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
        "timeline": [{"offset": e["offset"], "event": e["event"]} for e in tl],  # run-relative: no wall-clock
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
    out["issues"], out["recommendations"] = grounded(out["issues"], tl), grounded(out["recommendations"], tl)
    return {**out, "timeline": tl, "disclaimer": DISCLAIMER}, model
