"""Hospital routing agent (Google ADK on Vertex AI). The model reads the free-text report, decides which hospital
capabilities the patient needs, weighs ETA against beds, diversion and specialty fit, and picks the destination; the code
only guards it: the keyword baseline's critical capabilities may not be dropped, and the chosen hospital must be known,
free of diversion, have a bed and every required capability, otherwise a rule-based fallback is used. Returns the tool
trace for the UI. It never touches acuity or signal priority: the crew's confirmed tier comes in and stays as it was."""

import asyncio
import json
import os
import re
import uuid
from datetime import UTC, datetime

# ADK reads these; setdefault so the Cloud Run env wins (GCP_PROJECT / GEMINI_LOCATION already exist there)
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", os.environ.get("GCP_PROJECT", "green-corridor-2026"))
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", os.environ.get("GEMINI_LOCATION", "global"))

from google.genai import types

try:
    from google.adk.agents import LlmAgent
    from google.adk.planners import BuiltInPlanner
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    HAVE_ADK = True
except (
    ImportError
):  # light test envs skip the heavy ADK package; route() then always takes the rule-based fallback
    HAVE_ADK = False

import routes_api
from corridor import CORRIDORS, distance_m
from gemini import log, offline
from hospitals import CAPS, HOSPITALS, by_id, on_diversion
from telemetry import traced

TIMEOUT_S = 20
FALLBACK_SPEED_MPS = 8  # straight-line ETA when Routes has no answer
KEYWORDS = {  # complaint/transcript substrings -> capability
    "cath_lab": ("chest pain", "stemi", "cardiac", "heart attack"),
    "stroke_unit": ("stroke", "facial droop", "face droop", "slurred speech", "one-sided weakness"),
    "burns": ("burn",),
    "trauma": ("trauma", "fracture", "bleed", "accident", "injur", "crash"),
}
CRITICAL = {
    "cath_lab",
    "stroke_unit",
    "burns",
}  # time-critical baseline hits the model may add to but never drop


def list_hospitals(corridor: str) -> dict:
    """List the hospitals in a corridor's mock roster: id, name, lat, lng, capabilities, beds_available, diversion,
    trauma_level and cath_lab_door_to_balloon_min.

    Args:
        corridor: corridor id, "blr" or "hyd".
    """
    return {"hospitals": HOSPITALS.get(corridor, [])}


def eta_to(lat: float, lng: float, dest_lat: float, dest_lng: float) -> dict:
    """Traffic-aware driving ETA in seconds from the ambulance position to a destination.

    Args:
        lat: ambulance latitude.
        lng: ambulance longitude.
        dest_lat: destination latitude.
        dest_lng: destination longitude.
    """
    a, b = (lat, lng), (dest_lat, dest_lng)
    km = round(distance_m(a, b) / 1000, 1)  # straight line, whatever the ETA source
    line = {
        "eta_s": round(distance_m(a, b) / FALLBACK_SPEED_MPS),
        "distance_km": km,
        "source": "straight_line_estimate",
    }
    if offline():  # no Routes call: straight line
        return line
    r = routes_api.traffic_to_point(a, b, key=("eta_to", a, b), ttl=30)
    if r["duration_s"] is not None:
        return {
            **line,
            "eta_s": round(max(r["duration_s"] - r["age_s"], 0)),
            "source": "routes_traffic_aware",
        }
    return line


def check_diversion(hospital_id: str, tool_context=None) -> dict:
    """Whether a hospital is on diversion right now (not accepting ambulance arrivals). Mock live feed: Apollo is on
    diversion for about 30 % of runs (keyed by run id), the same answer every time for one run.

    Args:
        hospital_id: id from list_hospitals.
    """
    h = by_id(hospital_id)
    if not h:
        return {"hospital_id": hospital_id, "error": "unknown_hospital"}
    incident = tool_context.state.get("incident_id") if tool_context else None
    return {"hospital_id": h["id"], "on_diversion": on_diversion(h, incident)}


def _age(fields: dict):
    if fields.get("age") is not None:
        try:
            return float(fields["age"])
        except (TypeError, ValueError):
            pass
    m = re.search(r"(\d{1,3})[\s-]*(?:year|yr|y/o|yo)", _text(fields))
    return float(m.group(1)) if m else None


def _text(fields: dict) -> str:
    return " ".join(str(fields.get(k) or "") for k in ("complaint", "incident_type", "transcript_en")).lower()


def _baseline(fields: dict) -> set[str]:
    text, age = _text(fields), _age(fields)
    need = {cap for cap, words in KEYWORDS.items() if any(w in text for w in words)}
    if (age is not None and age < 14) or "child" in text or "paediatric" in text:
        need.add("paediatrics")
    return need


def required_capabilities(confirmed_tier: str, fields: dict) -> dict:
    """Validation baseline: the keyword-table guess at the capabilities needed, to compare your own reading of the
    report against. You may add to it; you may not drop anything listed under critical; justify any deviation. The
    confirmed tier is context only and is never changed.

    Args:
        confirmed_tier: the crew's confirmed acuity tier (critical, urgent, stable).
        fields: extracted patient fields (complaint, transcript_en, age, vitals ...), passed through unchanged.
    """
    need = _baseline(fields or {})
    return {"confirmed_tier": confirmed_tier, "required": sorted(need), "critical": sorted(need & CRITICAL)}


INSTRUCTION = """You route an ambulance with a patient on board to a hospital. You make the decisions; the tools give facts and
a server check rejects unsafe answers. Work in this order:
1. required_capabilities(confirmed_tier, fields): pass the tier and fields exactly as given in the request. It returns a
   keyword-table BASELINE ("required") and the part of it that is "critical". The baseline is a cheap guess, not the answer.
2. Read the complaint, transcript_en and the other fields yourself and decide which capabilities the patient needs, from
   exactly this vocabulary: cath_lab, stroke_unit, trauma, burns, paediatrics, icu, dialysis, obstetrics. Add what the
   baseline missed (icu for shock or ventilation, dialysis for a renal patient, obstetrics for a pregnancy ...). Drop a
   baseline item only when the report clearly contradicts it (a nosebleed is not trauma). You may NEVER drop an item the
   baseline lists as critical. Each capability you require needs a one-line reason; each baseline item you drop needs one.
3. list_hospitals(corridor): capabilities, beds_available, diversion, trauma_level, cath_lab_door_to_balloon_min.
4. check_diversion(hospital_id) for each hospital you seriously consider. Never choose one that is on diversion; if your
   first choice is, say so and re-plan to the next best.
5. eta_to(lat, lng, dest_lat, dest_lng) for each hospital that has EVERY capability you require, beds_available > 0 and is
   not on diversion. The result has eta_s and distance_km.
Then weigh ETA against beds, diversion and how well the specialty fits (door-to-balloon time for a cardiac case, trauma
level for major trauma). The nearest hospital is not always the right one: choose a farther one when the nearer is on
diversion, has almost no beds or a weaker specialty match, and say why. Never choose a hospital missing a required
capability, with no beds or on diversion. Never change or comment on the acuity tier; it is the crew's decision. Reply with
ONLY a JSON object:
{"capabilities": [{"capability": "cath_lab", "reason": "<one line>"}], "dropped": [{"capability": "<baseline item>", "reason": "<one line>"}],
 "destination": "<hospital name>", "hospital_id": "<id>", "eta_s": <int>, "reasons": ["<sentence 1>", "<sentence 2>"],
 "alternatives": [{"hospital_id": "<id>", "eta_s": <int>, "why_not": "<one line>"}], "confidence": <0 to 1>}
"dropped" is [] when you drop nothing. The two reasons are exactly two plain sentences: which capabilities and beds made it
eligible, and why it beat the others. "alternatives" are the top two hospitals you rejected, most plausible first."""


def router_model() -> str:
    """The routing agent runs on GEMINI_TEXT_MODEL, like the brief and the report (GEMINI_MODEL is the extraction model)."""
    return os.environ.get("GEMINI_TEXT_MODEL", "gemini-3-flash-preview")


hospital_router = (
    LlmAgent(
        name="hospital_router",
        model=router_model(),
        instruction=INSTRUCTION,
        tools=[list_hospitals, eta_to, required_capabilities, check_diversion],
        planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)),
    )
    if HAVE_ADK
    else None
)  # tool-calling, not deep reasoning: keeps the confirm tap fast


def _hospital_at(lat, lng):
    return next((h for hs in HOSPITALS.values() for h in hs if (h["lat"], h["lng"]) == (lat, lng)), None)


def _summary(name, args, res):
    if name == "list_hospitals":
        return f"{len(res.get('hospitals', []))} hospitals: " + ", ".join(
            h["id"] for h in res.get("hospitals", [])
        )
    if name == "eta_to":
        return f"{res.get('eta_s')} s, {res.get('distance_km')} km"
    if name == "check_diversion":
        return "on diversion" if res.get("on_diversion") else "accepting"
    if name == "required_capabilities":
        return ", ".join(res.get("required", [])) or "none"
    return json.dumps(res)[:120]


def _trace_entry(call, res):
    name, args = call.name, dict(call.args or {})
    label = args.get("corridor") or args.get("confirmed_tier")
    if name == "eta_to":
        h = _hospital_at(args.get("dest_lat"), args.get("dest_lng"))
        label = h["name"] if h else f"{args.get('dest_lat')},{args.get('dest_lng')}"
    if name == "check_diversion":
        label = (by_id(args.get("hospital_id")) or {}).get("name") or args.get("hospital_id")
    out = _summary(name, args, res)
    return {"tool": name, "args": args, "result": out, "text": f"called {name}({label or ''}) → {out}"}


def _origin(run):
    t = (run.get("ticks") or [None])[-1]
    if t:
        return t["lat"], t["lng"]
    j = CORRIDORS[run["corridor"]]["junctions"][0]  # no tick yet: the corridor's start
    return j["lat"], j["lng"]


async def _ask(run, origin):
    f = run.get("fields") or {}
    msg = (
        f"Corridor: {run['corridor']}\nAmbulance position: lat {origin[0]}, lng {origin[1]}\n"
        f"confirmed_tier: {run.get('confirmed_tier')}\nfields (JSON): {json.dumps(f)}"
    )
    svc = InMemorySessionService()
    runner = Runner(app_name="corridor", agent=hospital_router, session_service=svc)
    sid = uuid.uuid4().hex
    await svc.create_session(
        app_name="corridor", user_id="api", session_id=sid, state={"incident_id": run.get("id")}
    )  # check_diversion reads the incident from here
    calls, trace, final = {}, [], ""
    async for ev in runner.run_async(
        user_id="api", session_id=sid, new_message=types.Content(role="user", parts=[types.Part(text=msg)])
    ):
        for p in (ev.content.parts or []) if ev.content else []:
            if p.function_call:
                calls[p.function_call.id] = p.function_call
            elif p.function_response:
                r = p.function_response
                trace.append(_trace_entry(calls[r.id], r.response or {}))
            elif p.text and ev.is_final_response():
                final += p.text
    return final, trace


class InvalidChoice(Exception):
    """A guard tripped: `guard` is the name recorded in the trace, `detail` says what."""

    def __init__(self, guard, detail=""):
        super().__init__(guard, detail)
        self.guard, self.detail = guard, detail


def _tool_eta(trace, h):
    """The last eta_to result for hospital h, in seconds, or None if the model never asked."""
    etas = [
        t["result"]
        for t in trace
        if t.get("tool") == "eta_to"
        and (t["args"].get("dest_lat"), t["args"].get("dest_lng")) == (h["lat"], h["lng"])
    ]
    return int(etas[-1].split()[0]) if etas else None


def _reasoned(items, what):
    """[{capability, reason}] from the model -> {capability: reason}; an unknown capability is rejected."""
    out = {}
    for e in items or []:
        cap = e.get("capability") if isinstance(e, dict) else None
        if cap not in CAPS:
            raise InvalidChoice("unknown_capability", f"{what}: {cap}")
        out[cap] = str(e.get("reason") or "").strip()
    return out


def _capabilities(out, baseline):
    """The model's capability decision against the keyword baseline: it may add (with a reason) and may drop a
    non-critical item (with a reason), never a critical one. Returns (capabilities, dropped) as {capability: reason}."""
    caps, dropped = _reasoned(out.get("capabilities"), "required"), _reasoned(out.get("dropped"), "dropped")
    if gone := (baseline & CRITICAL) - set(caps):
        raise InvalidChoice("dropped_baseline_capability", ", ".join(sorted(gone)))
    unexplained = [c for c in set(caps) - baseline if not caps[c]] + [
        c for c in baseline - set(caps) if not dropped.get(c)
    ]
    if unexplained:
        raise InvalidChoice("unjustified_deviation", ", ".join(sorted(unexplained)))
    return caps, dropped


def _capability_step(baseline, caps, dropped):
    """One trace line showing what the model decided against the baseline."""
    parts = [f"{c} ({caps[c] or 'baseline'})" for c in sorted(caps)]
    text = "capabilities: " + ("; ".join(parts) or "none")
    if added := sorted(set(caps) - baseline):
        text += f". Added to baseline: {', '.join(added)}"
    if dropped:
        text += ". Dropped from baseline: " + "; ".join(f"{c} ({r})" for c, r in sorted(dropped.items()))
    return {"step": "capabilities", "text": text}


def _validated(final, trace, corridor, baseline, incident_id=None):
    out = json.loads(re.sub(r"^```(?:json)?|```$", "", final.strip(), flags=re.M).strip())
    caps, dropped = _capabilities(out, baseline)
    need = set(caps) | (baseline & CRITICAL)
    h = by_id(out.get("hospital_id"))
    if not h or h not in HOSPITALS[corridor]:
        raise InvalidChoice("ineligible_choice", f"unknown hospital {out.get('hospital_id')}")
    if on_diversion(h, incident_id) or h["beds_available"] < 1 or not need <= set(h["capabilities"]):
        raise InvalidChoice("ineligible_choice", f"{h['id']} is on diversion, full or missing a capability")
    eta = _tool_eta(trace, h)
    if eta is None:  # the tool's number beats the model's restatement; only without one, take the model's
        eta = int(out["eta_s"])
    alternatives: list[dict] = []
    for a in out.get("alternatives") or []:
        alt = by_id(a.get("hospital_id")) if isinstance(a, dict) else None
        if (
            alt
            and alt in HOSPITALS[corridor]
            and alt is not h
            and all(alt["id"] != x["hospital_id"] for x in alternatives)
        ):
            alt_eta = _tool_eta(trace, alt)
            if alt_eta is None and isinstance(a.get("eta_s"), int | float):
                alt_eta = int(a["eta_s"])
            alternatives.append(
                {"hospital_id": alt["id"], "eta_s": alt_eta, "why_not": str(a.get("why_not") or "")[:200]}
            )
    try:
        confidence = min(max(float(out["confidence"]), 0.0), 1.0)
    except (KeyError, TypeError, ValueError):
        confidence = None
    return {
        "destination": h["name"],
        "hospital_id": h["id"],
        "eta_s": eta,
        "reasons": [str(r) for r in out["reasons"]][:2],
        "capabilities": [{"capability": c, "reason": r} for c, r in sorted(caps.items())],
        "alternatives": alternatives[:2],
        "confidence": confidence,
        "trace": [*trace, _capability_step(baseline, caps, dropped)],
    }


def _why_not(h, eta, chosen_eta, need, incident_id):
    if on_diversion(h, incident_id):
        return "on diversion"
    if h["beds_available"] < 1:
        return "no beds available"
    if missing := need - set(h["capabilities"]):
        return f"lacks {', '.join(sorted(missing))}"
    return f"{eta - chosen_eta} s further than the chosen hospital"


def _fallback(run, need, origin, why, trace=None):
    corridor, incident = run["corridor"], run.get("id")
    free = [h for h in HOSPITALS[corridor] if h["beds_available"] > 0 and not on_diversion(h, incident)]
    ok = [h for h in free if need <= set(h["capabilities"])]
    h = min(ok or free or HOSPITALS[corridor], key=lambda h: distance_m(origin, (h["lat"], h["lng"])))
    why_not = (
        ""
        if ok
        else " No hospital has every required capability, a bed and no diversion, so this is only the nearest that is free."
    )
    line = {
        x["id"]: round(distance_m(origin, (x["lat"], x["lng"])) / FALLBACK_SPEED_MPS)
        for x in HOSPITALS[corridor]
    }
    others = sorted((x for x in HOSPITALS[corridor] if x is not h), key=lambda x: line[x["id"]])[:2]
    return {
        "destination": h["name"],
        "hospital_id": h["id"],
        "eta_s": eta_to(origin[0], origin[1], h["lat"], h["lng"])["eta_s"],
        "reasons": [
            f"Routing agent unavailable ({why}); rule-based fallback.",
            f"Nearest hospital with required capabilities {sorted(need) or 'none'}, a bed and no diversion.{why_not}",
        ],
        "capabilities": [{"capability": c, "reason": "keyword baseline"} for c in sorted(need)],
        "alternatives": [
            {
                "hospital_id": x["id"],
                "eta_s": line[x["id"]],
                "why_not": _why_not(x, line[x["id"]], line[h["id"]], need, incident),
            }
            for x in others
        ],
        "confidence": None,  # no model judgment behind a rule-based pick
        "trace": trace or [{"fallback": why}],
    }


def route(run: dict) -> dict:
    """run: the run doc plus optional `fields` (extracted patient fields). Returns {destination, hospital_id, eta_s,
    reasons, capabilities, alternatives, confidence, trace}. Never raises: any agent failure, timeout, dropped critical
    capability or ineligible choice falls back to the nearest eligible hospital (a guard shows as a trace entry)."""
    baseline = _baseline(run.get("fields") or {})
    origin = _origin(run)
    if offline() or not HAVE_ADK:
        return _fallback(run, baseline, origin, "offline_ai" if offline() else "adk_missing")
    trace: list = []
    try:
        final, trace = asyncio.run(asyncio.wait_for(_ask(run, origin), TIMEOUT_S))
        return _validated(final, trace, run["corridor"], baseline, run.get("id"))
    except InvalidChoice as e:
        log(event="routing_guard", run_id=run.get("id"), guard=e.guard, detail=e.detail[:200])
        guard = {"guard": e.guard, "text": f"guard: {e.guard} ({e.detail}); rule-based fallback"}
        return _fallback(run, baseline, origin, f"safety check: {e.guard}", [*trace, guard])
    except Exception as e:  # ponytail: broad on purpose, a crew-facing decision must always come back
        log(event="routing_fallback", run_id=run.get("id"), error=type(e).__name__, detail=str(e)[:200])
        return _fallback(run, baseline, origin, type(e).__name__)


@traced("agent.route")
def apply(ref):
    """Route the run at `ref` and write runs/{id}.routing (plus destination if it was empty or itself routed).
    Returns the routing, or None when the run is not a confirmed ambulance run on a corridor with a roster."""
    run = ref.get().to_dict()
    if (
        run.get("vehicle_type") != "ambulance"
        or not run.get("confirmed_tier")
        or run.get("corridor") not in HOSPITALS
    ):
        return None
    fields, said = {}, []
    for d in sorted(ref.collection("log").stream(), key=lambda d: int(d.id)):
        f = d.to_dict().get("fields") or {}
        said.append(f.get("transcript_en") or "")
        fields.update({k: v for k, v in f.items() if v is not None and k != "transcript_en"})
    fields["transcript_en"] = " ".join(said)[:600]
    out = route({**run, "id": ref.id, "fields": fields})
    out["decided_at"] = datetime.now(UTC)
    scenario = bool(
        run.get("scenario")
    )  # a replay keeps its corridor hospital: routing is recorded, not applied
    out["applied"] = not scenario
    if scenario:
        out["reason"] = "scenario run keeps corridor hospital"
    upd = {"routing": out}
    cur = run.get("destination")
    if not scenario and (cur is None or cur.get("name") == (run.get("routing") or {}).get("destination")):
        h = by_id(out["hospital_id"])
        upd["destination"] = {"name": h["name"], "lat": h["lat"], "lng": h["lng"]}
    ref.update(upd)
    log(
        event="routed",
        run_id=ref.id,
        hospital_id=out["hospital_id"],
        eta_s=out["eta_s"],
        tools=len(out["trace"]),
    )
    return out
