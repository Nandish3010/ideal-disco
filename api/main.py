import base64
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.api_core.exceptions import GoogleAPIError
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore import DELETE_FIELD, SERVER_TIMESTAMP, Query
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field

import acuity
import agent
import brief
import gemini
import leadtime
import priority
import report
import routes_api
from corridor import CORRIDORS, SCENARIOS, bearing, distance_m, junctions_ahead, locate
from firestore_client import db
from gemini import ExtractionFailed, extract, log
from hospitals import by_id
from signal_adapter import SimAdapter
from tts import speak, store_photo, translate

app = FastAPI(title="corridor-api")
# ponytail: demo, no auth, any origin
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
TIERS = {"critical", "urgent", "stable", "fire", "fire_with_trapped", "police", "police_with_incident"}


def todo(name: str) -> JSONResponse:
    return JSONResponse({"todo": name}, status_code=501)


def err(status: int, code: str, **kw) -> JSONResponse:
    return JSONResponse({"error": code, **kw}, status_code=status)


@app.exception_handler(GoogleAPIError)
def firestore_down(request, exc):
    log(event="firestore_error", path=request.url.path, error=type(exc).__name__, detail=str(exc)[:200])
    return err(503, "store_unavailable")


class Bind(BaseModel):
    plate: str
    device_id: str


class Incident(BaseModel):
    type: str
    severity_note: str = ""


class RunReq(BaseModel):
    action: str  # start | end
    plate: Optional[str] = None
    incident_id: Optional[str] = None
    corridor: Optional[str] = None
    destination: Optional[dict] = None
    source: str = "gps"
    run_id: Optional[str] = None


class Triage(BaseModel):
    run_id: str
    vehicle_type: Optional[str] = None
    text: Optional[str] = None
    audio_b64: Optional[str] = None
    image_b64: Optional[str] = None  # photo of a monitor or ECG strip; mime is then image/jpeg|png|webp
    mime: Optional[str] = None
    lang_hint: Optional[str] = None
    kind: Optional[str] = None  # /log only


class Confirm(BaseModel):
    tier: str


@app.get("/health")
def health():
    return {"ok": True, "model": os.environ.get("GEMINI_MODEL")}


@app.post("/vehicles/bind")
def vehicles_bind(b: Bind):
    ref = db.collection("vehicles").document(b.plate)
    v = ref.get()
    if not v.exists or not v.to_dict().get("active"):
        log(event="bind_rejected", plate=b.plate)
        return err(404, "unregistered_vehicle")
    ref.update({"bound_device_id": b.device_id})
    return {"plate": b.plate, **v.to_dict(), "bound_device_id": b.device_id}


@app.post("/incidents")
def incidents(i: Incident):
    iid = "INC-" + uuid.uuid4().hex[:6].upper()
    db.collection("incidents").document(iid).set(
        {"type": i.type, "severity_note": i.severity_note, "created_at": datetime.now(timezone.utc), "state": "open"})
    return {"incident_id": iid}


@app.post("/runs")
def runs(r: RunReq):
    if r.action == "end":
        ref = db.collection("runs").document(r.run_id or "-")
        if not ref.get().exists:
            return err(404, "unknown_run")
        ref.update({"state": "ended", "ahead_ids": []})
        log(event="run_ended", run_id=r.run_id)
        return {"run_id": r.run_id, "state": "ended", "report": report.write(r.run_id, ref)}
    if r.action != "start" or not (r.plate and r.incident_id and r.corridor):
        return err(400, "bad_request", detail="start needs plate, incident_id, corridor")
    v = db.collection("vehicles").document(r.plate).get()
    inc = db.collection("incidents").document(r.incident_id).get()
    if not (v.exists and v.to_dict().get("active")):
        return err(403, "unregistered_vehicle")
    if not (inc.exists and inc.to_dict().get("state") == "open"):
        return err(403, "no_active_incident")
    run_id = "run-" + uuid.uuid4().hex[:8]
    db.collection("runs").document(run_id).set({
        "vehicle_plate": r.plate, "vehicle_type": v.to_dict()["type"], "incident_id": r.incident_id,
        "corridor": r.corridor, "destination": r.destination, "source": r.source, "state": "en_route",
        "patient_on_board": False, "brief_fired": False, "started_at": datetime.now(timezone.utc)})
    log(event="run_started", run_id=run_id, plate=r.plate)
    return {"run_id": run_id}


def _extract_and_log(t: Triage, interventions=False):
    """Returns (run, fields, entry_ref) or a JSONResponse error."""
    run_ref = db.collection("runs").document(t.run_id)
    run = run_ref.get()
    if not run.exists:
        return err(404, "unknown_run")
    run = run.to_dict()
    audio = base64.b64decode(t.audio_b64) if t.audio_b64 else None
    image = base64.b64decode(t.image_b64) if t.image_b64 else None
    if not (audio or image or t.text):
        return err(400, "bad_request", detail="audio_b64, image_b64 or text required")
    if image and (audio or t.mime not in IMAGE_MIMES):
        return err(400, "bad_request", detail=f"image_b64 takes mime {sorted(IMAGE_MIMES)} and no audio_b64")
    try:
        fields = extract(audio, t.mime, t.text, t.vehicle_type or run["vehicle_type"], t.lang_hint, run_id=t.run_id,
                        interventions=interventions, image_bytes=image)
    except ExtractionFailed:
        log(event="extraction_failed", run_id=t.run_id)
        return err(422, "extraction_failed", fallback="form")
    given = fields.pop("interventions", [])  # kept on the entry, not inside fields
    coll = run_ref.collection("log")
    n = len(list(coll.stream()))  # ponytail: count-based index, racy under concurrent writers
    photo_url = store_photo(image, t.mime, f"photos/{t.run_id}/{n}.jpg") if image else None  # None: upload failed, entry still saved
    coll.document(str(n)).set({
        "t": datetime.now(timezone.utc), "kind": t.kind or ("photo" if image else "voice" if audio else "form"),
        "transcript_en": fields["transcript_en"], "fields": fields, "interventions": given, "confirmed": False,
        **({"photo_url": photo_url} if image else {})})
    return run, fields, run_ref, n, given, photo_url


@app.post("/triage")
def triage(t: Triage):
    out = _extract_and_log(t)
    if isinstance(out, JSONResponse):
        return out
    run, fields, run_ref, _, _, photo_url = out
    vtype = t.vehicle_type or run["vehicle_type"]
    tier = acuity.tier({**fields, "incident_id": run.get("incident_id")}, vtype)
    run_ref.update({"acuity_tier": tier})
    log(event="triage", run_id=t.run_id, suggested_tier=tier)
    return {"fields": fields, "transcript_en": fields["transcript_en"], "suggested_tier": tier,
            **({"photo_url": photo_url} if t.image_b64 else {})}


@app.post("/log")
def log_entry(t: Triage):
    out = _extract_and_log(t, interventions=True)
    if isinstance(out, JSONResponse):
        return out
    _, fields, _, n, given, photo_url = out
    return {"n": n, "transcript_en": fields["transcript_en"], "fields": fields, "interventions": given, "confirmed": False,
            **({"photo_url": photo_url} if t.image_b64 else {})}


@app.post("/runs/{run_id}/confirm")
def confirm(run_id: str, c: Confirm, bg: BackgroundTasks):
    if c.tier not in TIERS:
        return err(400, "bad_tier", detail=sorted(TIERS))
    ref = db.collection("runs").document(run_id)
    if not ref.get().exists:
        return err(404, "unknown_run")
    ref.update({"confirmed_tier": c.tier, "patient_on_board": True})
    log(event="tier_confirmed", run_id=run_id, tier=c.tier)
    bg.add_task(agent.apply, ref)  # hospital routing agent after the response (Cloud Run runs with --no-cpu-throttling); the UI reads runs/{id}.routing live
    return {"run_id": run_id, "confirmed_tier": c.tier, "patient_on_board": True, "routing": None}


class RouteReq(BaseModel):
    run_id: str


@app.post("/route")
def route(r: RouteReq):
    ref = db.collection("runs").document(r.run_id)
    if not ref.get().exists:
        return err(404, "unknown_run")
    return agent.apply(ref) or err(409, "not_routable", detail="needs a confirmed ambulance run on a corridor with a roster")


def write_brief(run_id, run_ref, run, entries):
    """Generate from the log and store briefs/{run_id}; marks the run's brief as fired. Raises ExtractionFailed."""
    b, model = brief.generate(run, entries, run_id=run_id)
    doc = {**b, "disclaimer": brief.DISCLAIMER, "generated_at": datetime.now(timezone.utc), "model": model}
    db.collection("briefs").document(run_id).set(doc)
    run_ref.update({"brief_fired": True, "brief_due": False})
    log(event="brief_written", run_id=run_id, model=model)
    return doc


def log_entries(run_ref):
    return [d.to_dict() for d in sorted(run_ref.collection("log").stream(), key=lambda d: int(d.id))]


class BriefReq(BaseModel):
    run_id: str


@app.post("/brief")
def brief_endpoint(b: BriefReq):
    run_ref = db.collection("runs").document(b.run_id)
    run = run_ref.get()
    if not run.exists:
        return err(404, "unknown_run")
    entries = log_entries(run_ref)
    if not entries:
        return err(422, "no_log_entries", detail="nothing to brief yet")
    try:
        return write_brief(b.run_id, run_ref, run.to_dict(), entries)
    except ExtractionFailed:
        log(event="brief_error", run_id=b.run_id, via="endpoint")
        return err(502, "brief_failed")


class Loc(BaseModel):
    run_id: str
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    speed_mps: float = Field(ge=0)
    heading: Optional[float] = None  # degrees; derived from the previous tick when absent
    t: Optional[datetime] = None  # tick time; server time when absent
    source: str = Field("gps", pattern="^(gps|sim)$")


LIVE = {"en_route", "off_route", "stale"}  # ticks revive stale and off_route runs; ended/arrived get 403
OFF_ROUTE_M, STALE_S, BRIEF_ETA_S, MIN_TICK_GAP_S, ARRIVE_M = 80, 30, 300, 5, 100
LABEL = {"ambulance": "AMBULANCE", "fire": "FIRE ENGINE", "police": "POLICE"}
COMPASS = {"N": "north", "NE": "north-east", "E": "east", "SE": "south-east", "S": "south", "SW": "south-west",
           "W": "west", "NW": "north-west"}


def alert_text(run, stage, jam_m, approach, exit_move, eta_s):
    vt = run["vehicle_type"]
    tier = run.get("confirmed_tier") or run.get("acuity_tier") or ("unconfirmed" if vt == "ambulance" else "")
    tier = tier.replace("_", " ").upper().replace(vt.upper(), "").strip()
    who = " ".join(x for x in (LABEL[vt], tier) if x)
    queue = f"{round(jam_m)} m queue" if jam_m else "no queue"
    move = "going STRAIGHT" if exit_move == "straight" else f"turning {exit_move.upper()}"
    arrives = f"{round(eta_s)} s" if eta_s < 60 else f"{round(eta_s / 60)} min"
    head = {"STOP": "STOP CROSS TRAFFIC · ", "UPDATE": "UPDATE · "}.get(stage, "")
    return f"{head}{who} · {queue} on your {COMPASS.get(approach, approach)} approach · {move} · arrives in {arrives}"


def contender(run_id, r, eta_s, approach):
    """Priority-engine row if this run may preempt, else None. Ambulances need the crew's confirmed tier and a patient on
    board; fire and police need an incident (always true for a started run)."""
    vt = r["vehicle_type"]
    if vt == "ambulance":
        if not (r.get("confirmed_tier") and r.get("patient_on_board")):
            return None
        tier = r["confirmed_tier"]
    elif r.get("incident_id"):
        tier = r.get("confirmed_tier") or acuity.tier({"incident_id": r["incident_id"]}, vt)
    else:
        return None
    return {"run_id": run_id, "vehicle_type": vt, "tier": tier, "eta_s": eta_s, "approach": approach}


def rationale(jid, seq, lang):
    """Gemini's one-line 'why this order' on the phase, English plus the junction language. Failure: omit and log.
    Always rewritten (deleted when fewer than 2 vehicles) so a stale line never outlives its sequence."""
    out = {"phase.rationale": DELETE_FIELD, "phase.rationale_local": DELETE_FIELD}
    if len(seq) >= 2:
        try:
            en = gemini.explain_sequence(
                [{k: c[k] for k in ("vehicle_type", "tier", "approach", "offset_s")} for c in seq], "en")
            out["phase.rationale"] = en
            out["phase.rationale_local"] = translate(en, lang)
        except (genai_errors.APIError, GoogleAPIError) as e:
            log(event="rationale_error", junction_id=jid, error=type(e).__name__, detail=str(e)[:200])
    db.collection("junctions").document(jid).update(out)


def preempt(run_id, run, jid, approach, eta_s, clear_s, stage, lang):
    me = contender(run_id, run, eta_s, approach)
    if me is None:
        return None
    rows = [me]
    for d in db.collection("runs").where(filter=FieldFilter("ahead_ids", "array_contains", jid)).limit(20).stream():
        r = d.to_dict()
        if d.id != run_id and r.get("state") == "en_route" and jid in (r.get("ahead") or {}):
            c = contender(d.id, r, r["ahead"][jid]["eta_s"], r["ahead"][jid]["approach"])
            if c:
                rows.append(c)
    seq = priority.sequence(rows)
    SimAdapter(db).request_green(
        jid, seq[0]["approach"], clear_s + 30 + seq[-1]["offset_s"], [c["run_id"] for c in seq],
        [{"run_id": c["run_id"], "offset_s": c["offset_s"], "approach": c["approach"]} for c in seq])
    sequence = [{"run_id": c["run_id"], "offset_s": c["offset_s"]} for c in seq]
    rationale(jid, seq, lang)
    db.collection("audit").add({"run_id": run_id, "junction_id": jid, "action": "preempt_requested", "stage": stage,
                                "approach": seq[0]["approach"], "sequence": sequence, "at": datetime.now(timezone.utc)})
    log(event="preempt_requested", run_id=run_id, junction_id=jid, sequence=sequence)
    return sequence


def mark_stale(now, skip):
    """Piggyback on any tick: runs with no tick for 30 s go stale. ponytail: newest 20 below the cutoff, no scheduler."""
    q = (db.collection("runs").where(filter=FieldFilter("last_tick_at", "<", now - timedelta(seconds=STALE_S)))
         .order_by("last_tick_at", direction=Query.DESCENDING).limit(20))
    for d in q.stream():
        if d.id != skip and d.to_dict().get("state") == "en_route":
            d.reference.update({"state": "stale", "ahead_ids": []})
            log(event="run_stale", run_id=d.id)


ESCALATE_S = 20


def escalate(now, mine, others):
    """Piggyback on any tick: alerts older than 20 s with no ACK are flagged and audited. Cheap: only this run's alerts
    plus the runs it shared a preemption sequence with (and only those still en_route). ponytail: no scheduler, so a
    quiet system escalates on the next tick."""
    ids = list(mine)
    for rid in others:
        r = db.collection("runs").document(rid).get()
        if r.exists and r.to_dict().get("state") == "en_route":
            ids.append(rid)
    for rid in ids:
        q = (db.collection("runs").document(rid).collection("alerts")
             .where(filter=FieldFilter("acked_at", "==", None)).where(filter=FieldFilter("escalated", "==", False)))
        for d in q.stream():
            a = d.to_dict()
            if a.get("created_at") is None or (now - a["created_at"]).total_seconds() <= ESCALATE_S:
                continue
            d.reference.update({"escalated": True, "escalated_at": SERVER_TIMESTAMP})
            db.collection("audit").add({"run_id": rid, "junction_id": a["junction_id"], "action": "escalation",
                                        "alert_n": int(d.id), "stage": a["stage"], "at": now})
            log(event="escalation", run_id=rid, junction_id=a["junction_id"], alert_n=int(d.id))


@app.post("/location")
def location(l: Loc):
    ref = db.collection("runs").document(l.run_id)
    snap = ref.get()
    if not snap.exists:
        return err(404, "unknown_run")
    run = snap.to_dict()
    if run["state"] not in LIVE:
        return err(403, "run_not_active", state=run["state"])
    corridor = CORRIDORS.get(run.get("corridor"))
    if corridor is None:
        return err(400, "unknown_corridor", detail=str(run.get("corridor")))
    now = datetime.now(timezone.utc)
    t = l.t if l.t and l.t.tzinfo else (l.t.replace(tzinfo=timezone.utc) if l.t else now)
    me = (l.lat, l.lng)

    # tick history: last 12, at most one per 5 s so they span ~60 s
    prev = run.get("ticks") or []
    last = prev[-1] if prev else None
    heading = l.heading
    if heading is None:
        heading = bearing((last["lat"], last["lng"]), me) if last and distance_m((last["lat"], last["lng"]), me) > 5 else run.get("heading")
    tick = {"t": t, "lat": l.lat, "lng": l.lng, "speed_mps": l.speed_mps}
    ticks = (prev[:-1] if last and (t - last["t"]).total_seconds() < MIN_TICK_GAP_S else prev)[-11:] + [tick]
    window = [k["speed_mps"] for k in ticks if (t - k["t"]).total_seconds() <= 60]
    observed = sum(window) / len(window)

    # hospital route: ETA, polyline for junction and off-route detection. While off_route the old polyline stays pinned
    # so the state holds until the vehicle rejoins it (the cache is per instance; a restart heals it).
    dest = by_id((run.get("routing") or {}).get("hospital_id")) or run.get("destination") or corridor["hospital"]
    scenario = run.get("scenario") in SCENARIOS  # replays follow the corridor config, not Google's road choice
    if scenario:
        hosp = {"polyline_points": [], "steps": [], "age_s": 0, "duration_s": distance_m(me, (dest["lat"], dest["lng"])) / max(observed, 3)}
    else:
        hosp = routes_api.traffic_to_point(
            me, (dest["lat"], dest["lng"]), key=(l.run_id, "hospital"), ttl=1e9 if run["state"] == "off_route" else 30,
            steps=True, run_id=l.run_id, junction_id=None)
    pts = hosp["polyline_points"]
    off = locate(pts, me)[1] if pts else 0
    state = "off_route" if off > OFF_ROUTE_M else "en_route"
    eta_h = run.get("eta_hospital_s")
    if hosp["duration_s"] is not None and hosp["age_s"] < 120:  # older means a pinned route: not an ETA
        eta_h = round(max(hosp["duration_s"] - hosp["age_s"], 0))
    out = {"state": state, "next_junction": None, "approach": None, "jam_m": None, "eta_s": None, "stage": None,
           "exit_move": None, "eta_hospital_s": eta_h, "alerts_fired": [], "brief_due": bool(run.get("brief_due")),
           "observed_speed_60s": round(observed, 1), "traffic": None}
    upd = {"ticks": ticks, "last_tick_at": now, "source": l.source, "state": state, "heading": heading,
           "eta_hospital_s": eta_h, "next_junction_id": None}

    # every junction ahead is evaluated, not just the next: a long queue needs the cop warned minutes before the vehicle
    # reaches the junction, while nearer junctions are still to come. One Routes call per (run, junction) per 20 s.
    ahead = junctions_ahead(corridor, l.lat, l.lng, heading, pts) if state == "en_route" else []
    alerts = dict(run.get("alert_state") or {})
    n = run.get("alert_count", 0)
    upd["ahead"], upd["ahead_ids"] = {}, []
    contenders = set(run.get("contenders") or [])  # run ids met in a preemption sequence; their alerts get escalation-checked too
    for j, ap in ahead:
        jid, jc, dist = j["doc_id"], (j["lat"], j["lng"]), j["ahead_m"]
        if scenario:  # recorded spans, no Routes call; a junction with none recorded is NORMAL
            rec = SCENARIOS[run["scenario"]].get("recorded_spans", {}).get(jid) or [{"intervals": []}]
            intervals, routes_eta, traffic = rec[0]["intervals"], dist / max(observed, 3), "scenario"
        else:
            tr = routes_api.traffic_to_point(me, jc, key=(l.run_id, jid), ttl=20, run_id=l.run_id, junction_id=jid)
            intervals, traffic = tr["intervals"], "stale" if tr["stale"] else "live"
            routes_eta = max(tr["duration_s"] - tr["age_s"], 0) if tr["duration_s"] is not None else dist / max(observed, 3)
        jam_m = leadtime.jam_metres(intervals)
        clear_s = leadtime.clear_seconds(jam_m)
        eta_s = leadtime.blended_eta(routes_eta, dist, observed)
        stage = leadtime.stage(eta_s, clear_s)
        if stage is None and jam_m > 0 and jam_m >= dist - 25:  # vehicle is inside the queue: alert now
            stage = "PREPARE"
        if distance_m(me, jc) <= ap["radius_m"]:  # at the stop line
            stage = "STOP"
        if ap["bearing_err"] > 45:
            log(event="approach_bearing_mismatch", run_id=l.run_id, junction_id=jid, approach=ap["id"], err=round(ap["bearing_err"]))
        move = routes_api.exit_move(hosp["steps"], jc)
        upd["ahead"][jid] = {"eta_s": eta_s, "approach": ap["id"]}
        upd["ahead_ids"].append(jid)

        # alerts: PREPARE once, UPDATE if the queue grew > 100 m, STOP once
        s = dict(alerts.get(jid) or {})
        fire = None
        if stage == "STOP" and not s.get("stop"):
            fire = "STOP"
        elif stage == "PREPARE" and not s.get("prepare"):
            fire = "PREPARE"
        elif stage == "PREPARE" and not s.get("stop") and jam_m > s.get("jam_m", 0) + 100:
            fire = "UPDATE"
        if fire:
            text = alert_text(run, fire, jam_m, ap["id"], move, eta_s)
            audio_url, text_local = speak(text, corridor["lang"], f"alerts/{l.run_id}/{jid}/{fire}-{n}.mp3")  # None: text-only alert
            ref.collection("alerts").document(str(n)).set({
                "junction_id": jid, "approach": ap["id"], "stage": fire, "jam_m": round(jam_m), "eta_s": round(eta_s),
                "exit_move": move, "text": text, "text_local": text_local, "audio_url": audio_url, "acked_at": None,
                "escalated": False, "created_at": SERVER_TIMESTAMP})
            n += 1
            s.update({"prepare": True, "stop": s.get("stop") or fire == "STOP", "jam_m": jam_m})
            alerts[jid] = s
            upd.update({"alert_state": alerts, "alert_count": n})
            out["alerts_fired"].append({"junction": jid, "stage": fire})
            log(event="alert", run_id=l.run_id, junction_id=jid, stage=fire, jam_m=round(jam_m), eta_s=round(eta_s))
            seq = preempt(l.run_id, run, jid, ap["id"], eta_s, clear_s, fire, corridor["lang"])
            contenders.update(c["run_id"] for c in seq or [])
        if upd["next_junction_id"] is None:  # nearest junction ahead is what the response reports
            upd.update({"next_junction_id": jid, "next_approach": ap["id"], "next_eta_s": eta_s})
            out.update({"next_junction": jid, "approach": ap["id"], "jam_m": round(jam_m), "eta_s": round(eta_s),
                        "stage": stage, "exit_move": move, "traffic": traffic})
    upd["last_eval"] = {k: out[k] for k in ("next_junction", "approach", "jam_m", "eta_s", "stage", "exit_move", "traffic")}

    # brief: once per run at ETA <= 300 s (also the first tick of a short run). Needs log entries, else retried next tick;
    # on Gemini failure brief_due stays true and the hospital's Regenerate button (POST /brief) takes over.
    entries = []
    if eta_h is not None and eta_h <= BRIEF_ETA_S and not run.get("brief_fired") and not run.get("brief_due"):
        entries = log_entries(ref)
        upd["brief_due"] = out["brief_due"] = bool(entries)
    upd["contenders"] = sorted(contenders - {l.run_id})
    upd["distance_m"] = round(run.get("distance_m", 0) + (distance_m((last["lat"], last["lng"]), me) if last else 0))
    arrived = distance_m(me, (dest["lat"], dest["lng"])) <= ARRIVE_M
    if arrived:
        upd.update({"state": "arrived", "ahead_ids": [], "ahead": {}})
        out["state"] = "arrived"
    ref.update(upd)
    if entries:
        try:
            write_brief(l.run_id, ref, run, entries)
            out["brief_due"] = False
        except ExtractionFailed:
            log(event="brief_error", run_id=l.run_id, via="location")
    mark_stale(now, l.run_id)
    escalate(now, [l.run_id], upd["contenders"])
    if arrived:
        report.write(l.run_id, ref)
    return out


class Ack(BaseModel):
    run_id: str
    alert_n: int
    junction_id: str
    device_id: Optional[str] = None


@app.post("/ack")
def ack(a: Ack):
    ref = db.collection("runs").document(a.run_id).collection("alerts").document(str(a.alert_n))
    snap = ref.get()
    if not snap.exists or snap.to_dict()["junction_id"] != a.junction_id:
        return err(404, "unknown_alert")
    d = snap.to_dict()
    if d.get("acked_at"):  # idempotent: the first ACK stands
        acked, latency = d["acked_at"], d.get("ack_latency_s")
    else:
        acked = datetime.now(timezone.utc)
        latency = round(max((acked - d["created_at"]).total_seconds(), 0), 1) if d.get("created_at") else None
        ref.update({"acked_at": acked, "ack_latency_s": latency, "acked_by": a.device_id})
        log(event="ack", run_id=a.run_id, junction_id=a.junction_id, alert_n=a.alert_n, ack_latency_s=latency)
    # latency_s: alias the cop page reads today
    return {"ok": True, "acked_at": acked.isoformat(), "ack_latency_s": latency, "latency_s": latency}


class Duty(BaseModel):
    corridor: str
    junction_id: str  # "blr_j3" or "j3"
    device_id: str
    on: bool
    name: Optional[str] = None


@app.post("/duty")
def duty(d: Duty):
    c = CORRIDORS.get(d.corridor)
    if c is None:
        return err(400, "unknown_corridor", detail=d.corridor)
    jid = d.junction_id.removeprefix(d.corridor + "_")
    if jid not in {j["id"] for j in c["junctions"]}:
        return err(404, "unknown_junction", detail=d.junction_id)
    doc = {"device_id": d.device_id, "name": d.name, "on": d.on, "since": datetime.now(timezone.utc)}
    db.collection("duty").document(f"{d.corridor}_{jid}").set(doc)
    log(event="duty", junction_id=f"{d.corridor}_{jid}", device_id=d.device_id, on=d.on)
    return {**doc, "since": doc["since"].isoformat()}
