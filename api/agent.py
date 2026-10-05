"""Hospital routing agent (Google ADK on Vertex AI). Picks the destination hospital for a confirmed ambulance run from a
mock capability/bed roster plus traffic-aware ETAs, and returns its tool trace for the UI. It never touches acuity or
signal priority: the crew's confirmed tier comes in, the tier stays exactly as it was."""
import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timezone

# ADK reads these; setdefault so the Cloud Run env wins (GCP_PROJECT / GEMINI_LOCATION already exist there)
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", os.environ.get("GCP_PROJECT", "green-corridor-2026"))
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", os.environ.get("GEMINI_LOCATION", "global"))

from google.adk.agents import LlmAgent
from google.adk.planners import BuiltInPlanner
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

import routes_api
from corridor import CORRIDORS, distance_m
from gemini import log, offline
from hospitals import HOSPITALS, by_id

TIMEOUT_S = 20
FALLBACK_SPEED_MPS = 8  # straight-line ETA when Routes has no answer
KEYWORDS = {  # complaint/transcript substrings -> capability
    "cath_lab": ("chest pain", "stemi", "cardiac", "heart attack"),
    "stroke_unit": ("stroke", "facial droop", "face droop", "slurred speech", "one-sided weakness"),
    "burns": ("burn",),
    "trauma": ("trauma", "fracture", "bleed", "accident", "injur", "crash"),
}


def list_hospitals(corridor: str) -> dict:
    """List the hospitals in a corridor's mock roster, with id, name, lat, lng, capabilities and beds_available.

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
    if offline():  # no Routes call: straight line
        return {"eta_s": round(distance_m(a, b) / FALLBACK_SPEED_MPS), "source": "straight_line_estimate"}
    r = routes_api.traffic_to_point(a, b, key=("eta_to", a, b), ttl=30)
    if r["duration_s"] is not None:
        return {"eta_s": round(max(r["duration_s"] - r["age_s"], 0)), "source": "routes_traffic_aware"}
    return {"eta_s": round(distance_m(a, b) / FALLBACK_SPEED_MPS), "source": "straight_line_estimate"}


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


def required_capabilities(confirmed_tier: str, fields: dict) -> dict:
    """Deterministic mapping from the patient's reported fields to the hospital capabilities needed. The confirmed tier is
    context only and is never changed.

    Args:
        confirmed_tier: the crew's confirmed acuity tier (critical, urgent, stable).
        fields: extracted patient fields (complaint, transcript_en, age, vitals ...), passed through unchanged.
    """
    fields = fields or {}
    text, age = _text(fields), _age(fields)
    need = {cap for cap, words in KEYWORDS.items() if any(w in text for w in words)}
    if (age is not None and age < 14) or "child" in text or "paediatric" in text:
        need.add("paediatrics")
    return {"confirmed_tier": confirmed_tier, "required": sorted(need)}


INSTRUCTION = """You route an ambulance with a patient on board to a hospital. Work with the tools, in this order:
1. required_capabilities(confirmed_tier, fields): pass the tier and fields exactly as given in the request.
2. list_hospitals(corridor).
3. eta_to(lat, lng, dest_lat, dest_lng) once for each hospital that has EVERY required capability and beds_available > 0.
Choose the one of those with the lowest ETA. Never choose a hospital missing a required capability or with no beds. Never
change or comment on the acuity tier; it is the crew's decision. Reply with ONLY a JSON object:
{"destination": "<hospital name>", "hospital_id": "<id>", "eta_s": <int>, "reasons": ["<sentence 1>", "<sentence 2>"]}
The two reasons are exactly two plain sentences: which capabilities and beds made it eligible, and why it beat the others on ETA."""

hospital_router = LlmAgent(name="hospital_router", model=os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview"),
                           instruction=INSTRUCTION, tools=[list_hospitals, eta_to, required_capabilities],
                           planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(thinking_level="LOW")))  # tool-calling, not deep reasoning: keeps the confirm tap fast


def _hospital_at(lat, lng):
    return next((h for hs in HOSPITALS.values() for h in hs if (h["lat"], h["lng"]) == (lat, lng)), None)


def _summary(name, args, res):
    if name == "list_hospitals":
        return f"{len(res.get('hospitals', []))} hospitals: " + ", ".join(h["id"] for h in res.get("hospitals", []))
    if name == "eta_to":
        return f"{res.get('eta_s')} s"
    if name == "required_capabilities":
        return ", ".join(res.get("required", [])) or "none"
    return json.dumps(res)[:120]


def _trace_entry(call, res):
    name, args = call.name, dict(call.args or {})
    label = args.get("corridor") or args.get("confirmed_tier")
    if name == "eta_to":
        h = _hospital_at(args.get("dest_lat"), args.get("dest_lng"))
        label = h["name"] if h else f"{args.get('dest_lat')},{args.get('dest_lng')}"
    out = _summary(name, args, res)
    return {"tool": name, "args": args, "result": out, "text": f"called {name}({label or ''}) → {out}"}


def _origin(run):
    t = (run.get("ticks") or [None])[-1]
    if t:
        return t["lat"], t["lng"]
    j = CORRIDORS[run["corridor"]]["junctions"][0]  # no tick yet: the corridor's start
    return j["lat"], j["lng"]


async def _ask(run, need, origin):
    f = run.get("fields") or {}
    msg = (f"Corridor: {run['corridor']}\nAmbulance position: lat {origin[0]}, lng {origin[1]}\n"
           f"confirmed_tier: {run.get('confirmed_tier')}\nfields (JSON): {json.dumps(f)}")
    svc = InMemorySessionService()
    runner = Runner(app_name="corridor", agent=hospital_router, session_service=svc)
    sid = uuid.uuid4().hex
    await svc.create_session(app_name="corridor", user_id="api", session_id=sid)
    calls, trace, final = {}, [], ""
    async for ev in runner.run_async(user_id="api", session_id=sid,
                                     new_message=types.Content(role="user", parts=[types.Part(text=msg)])):
        for p in (ev.content.parts if ev.content else []):
            if p.function_call:
                calls[p.function_call.id] = p.function_call
            elif p.function_response:
                r = p.function_response
                trace.append(_trace_entry(calls[r.id], r.response or {}))
            elif p.text and ev.is_final_response():
                final += p.text
    return final, trace


class InvalidChoice(Exception):
    pass


def _validated(final, trace, corridor, need):
    out = json.loads(re.sub(r"^```(?:json)?|```$", "", final.strip(), flags=re.M).strip())
    h = by_id(out.get("hospital_id"))
    if not h or h not in HOSPITALS[corridor] or h["beds_available"] < 1 or not need <= set(h["capabilities"]):
        raise InvalidChoice(out.get("hospital_id"))
    etas = [t["result"] for t in trace if t["tool"] == "eta_to" and (t["args"].get("dest_lat"), t["args"].get("dest_lng")) == (h["lat"], h["lng"])]
    eta = int(etas[-1].split()[0]) if etas else int(out["eta_s"])  # the tool's number beats the model's restatement
    return {"destination": h["name"], "hospital_id": h["id"], "eta_s": eta, "reasons": [str(r) for r in out["reasons"]][:2],
            "trace": trace}


def _fallback(run, need, origin, why):
    hs = [h for h in HOSPITALS[run["corridor"]] if h["beds_available"] > 0]
    ok = [h for h in hs if need <= set(h["capabilities"])]
    h = min(ok or hs or HOSPITALS[run["corridor"]], key=lambda h: distance_m(origin, (h["lat"], h["lng"])))
    why_not = "" if ok else " No hospital has every required capability and a bed, so this is only the nearest with a bed."
    return {"destination": h["name"], "hospital_id": h["id"], "eta_s": eta_to(*origin, h["lat"], h["lng"])["eta_s"],
            "reasons": [f"Routing agent unavailable ({why}); rule-based fallback.",
                        f"Nearest hospital with required capabilities {sorted(need) or 'none'} and beds available.{why_not}"],
            "trace": [{"fallback": why}]}


def route(run: dict) -> dict:
    """run: the run doc plus optional `fields` (extracted patient fields). Returns {destination, hospital_id, eta_s,
    reasons, trace}. Never raises: any agent failure, timeout or invalid choice falls back to the nearest eligible hospital."""
    need = set(required_capabilities(run.get("confirmed_tier"), run.get("fields") or {})["required"])
    origin = _origin(run)
    if offline():
        return _fallback(run, need, origin, "offline_ai")
    try:
        final, trace = asyncio.run(asyncio.wait_for(_ask(run, need, origin), TIMEOUT_S))
        return _validated(final, trace, run["corridor"], need)
    except Exception as e:  # ponytail: broad on purpose, a crew-facing decision must always come back
        log(event="routing_fallback", run_id=run.get("id"), error=type(e).__name__, detail=str(e)[:200])
        return _fallback(run, need, origin, type(e).__name__)


def apply(ref):
    """Route the run at `ref` and write runs/{id}.routing (plus destination if it was empty or itself routed).
    Returns the routing, or None when the run is not a confirmed ambulance run on a corridor with a roster."""
    run = ref.get().to_dict()
    if run.get("vehicle_type") != "ambulance" or not run.get("confirmed_tier") or run.get("corridor") not in HOSPITALS:
        return None
    fields, said = {}, []
    for d in sorted(ref.collection("log").stream(), key=lambda d: int(d.id)):
        f = d.to_dict().get("fields") or {}
        said.append(f.get("transcript_en") or "")
        fields.update({k: v for k, v in f.items() if v is not None and k != "transcript_en"})
    fields["transcript_en"] = " ".join(said)[:600]
    out = route({**run, "id": ref.id, "fields": fields})
    out["decided_at"] = datetime.now(timezone.utc)
    scenario = bool(run.get("scenario"))  # a replay keeps its corridor hospital: routing is recorded, not applied
    out["applied"] = not scenario
    if scenario:
        out["reason"] = "scenario run keeps corridor hospital"
    upd = {"routing": out}
    cur = run.get("destination")
    if not scenario and (cur is None or cur.get("name") == (run.get("routing") or {}).get("destination")):
        h = by_id(out["hospital_id"])
        upd["destination"] = {"name": h["name"], "lat": h["lat"], "lng": h["lng"]}
    ref.update(upd)
    log(event="routed", run_id=ref.id, hospital_id=out["hospital_id"], eta_s=out["eta_s"], tools=len(out["trace"]))
    return out


if __name__ == "__main__":
    rc = lambda c, **f: required_capabilities("critical", {"complaint": c, **f})["required"]
    assert rc("chest pain radiating to left arm") == ["cath_lab"]
    assert rc("fracture", transcript_en="fracture, 10 year old") == ["paediatrics", "trauma"]
    assert rc("fracture", age=40) == ["trauma"] and rc("stroke signs") == ["stroke_unit"] and rc("burns > 20%") == ["burns"]
    assert rc("headache") == []
    # fallback needs no model: Jayadeva is nearest to Silk Board with cath_lab and beds; the child fracture needs Fortis
    origin = (12.9172, 77.6229)
    routes_api.URL = "http://127.0.0.1:9/x"  # no network: ETA falls back to straight line
    r = _fallback({"corridor": "blr"}, {"cath_lab"}, origin, "TimeoutError")
    assert r["hospital_id"] == "blr_jayadeva" and r["trace"] == [{"fallback": "TimeoutError"}], r
    assert _fallback({"corridor": "blr"}, {"trauma", "paediatrics"}, origin, "x")["hospital_id"] == "blr_fortis_bg"
    assert "only the nearest" in _fallback({"corridor": "blr"}, {"burns", "stroke_unit"}, origin, "x")["reasons"][1]
    # an agent answer naming a hospital that lacks a required capability is rejected
    bad = json.dumps({"hospital_id": "blr_jayadeva", "eta_s": 1, "reasons": []})
    try:
        _validated(bad, [], "blr", {"trauma"})
        raise SystemExit("accepted an ineligible hospital")
    except InvalidChoice:
        pass
    os.environ["OFFLINE_AI"] = "1"  # no model, no Routes: the fallback comes back at once
    r = route({"corridor": "blr", "confirmed_tier": "critical", "fields": {"complaint": "chest pain"}})
    assert r["hospital_id"] == "blr_jayadeva" and r["trace"] == [{"fallback": "offline_ai"}], r
    print("agent ok")
