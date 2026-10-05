"""Offline replay check: plays data/scenarios/blr-two-vehicles.json through a local API started with OFFLINE_AI=1 (no Gemini,
TTS, Translation, Routes or agent calls; Firestore is real). Run from api/:
    OFFLINE_AI=1 RATE_LIMIT_DISABLED=1 GOOGLE_APPLICATION_CREDENTIALS=<key> uvicorn main:app --port 8080
    python offline_replay.py [http://127.0.0.1:8080]
Writes test runs, alerts and reports to Firestore like any other run. Exits 1 if a check fails."""

import sys
from datetime import UTC, datetime, timedelta

import httpx
from google.cloud.firestore_v1.base_query import FieldFilter

from corridor import CORRIDORS, SCENARIOS
from firestore_client import db

API = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
NAME = "blr-two-vehicles"
SC, C = SCENARIOS[NAME], CORRIDORS["blr"]
ORDER = [f"blr_{j['id']}" for j in C["junctions"]]
http = httpx.Client(base_url=API, timeout=60)
checks: list[bool] = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def post(path, body):
    r = http.post(path, json=body)
    return r.status_code, r.json()


# setup: one run per scenario vehicle, tier set through /confirm (no /triage), one log entry so a brief could fire
runs = {}
for v in SC["vehicles"]:
    _, inc = post(
        "/incidents",
        {"type": "fire" if v["type"] == "fire" else "medical", "severity_note": "offline replay, synthetic"},
    )
    s, r = post(
        "/runs",
        {
            "action": "start",
            "plate": v["plate"],
            "incident_id": inc["incident_id"],
            "corridor": "blr",
            "destination": C["hospital"],
            "source": "sim",
            "scenario": NAME,
        },
    )
    assert s == 200, (s, r)
    rid = r["run_id"]
    db.collection("runs").document(rid).collection("log").document("0").set(
        {
            "t": datetime.now(UTC),
            "kind": "form",
            "transcript_en": "offline replay entry",
            "confirmed": False,
            "fields": {"complaint": "chest pain", "transcript_en": "offline replay entry"},
            "interventions": [],
        }
    )
    post(f"/runs/{rid}/confirm", {"tier": v["tier"]})
    runs[v["plate"]] = {
        "id": rid,
        "type": v["type"],
        "tier": v["tier"],
        "offset": v["start_offset_s"],
        "next": [],
        "ok": [],
        "brief_at": None,
    }
by_tier = {r["tier"]: r for r in runs.values()}
check(
    "/triage is 422 offline",
    post("/triage", {"run_id": by_tier["critical"]["id"], "text": "chest pain"})[0] == 422,
)

# replay every tick, vehicles interleaved by scenario time, no sleeping
events = sorted(
    ((v["start_offset_s"] + k["t"], v["plate"], k) for v in SC["vehicles"] for k in v["ticks"]),
    key=lambda e: e[:2],
)
base = datetime.now(UTC).replace(microsecond=0)
first_resp: dict = {}
for _n, (sim, plate, k) in enumerate(events):
    run = runs[plate]
    s, j = post(
        "/location",
        {
            "run_id": run["id"],
            "lat": k["lat"],
            "lng": k["lng"],
            "speed_mps": k["speed_mps"],
            "source": "sim",
            "t": (base + timedelta(seconds=sim)).isoformat(),
        },
    )
    if s != 200:  # arrived runs refuse later ticks
        continue
    run["ok"].append(sim)
    first_resp.setdefault(plate, j)
    if j["next_junction"] and (not run["next"] or run["next"][-1] != j["next_junction"]):
        run["next"].append(j["next_junction"])
    doc = db.collection("runs").document(run["id"]).get().to_dict()
    if run["type"] == "ambulance" and doc.get("brief_fired") and run["brief_at"] is None:
        run["brief_at"] = {
            "sim": sim,
            "tick": len(run["ok"]),
            "passed": doc["passed_junctions"],
            "distance_m": doc["distance_m"],
        }

# end the runs, collect reports
for r in runs.values():
    s, out = post("/runs", {"action": "end", "run_id": r["id"]})
    r["report"] = out["report"]
    r["alerts"] = [d.to_dict() for d in db.collection("runs").document(r["id"]).collection("alerts").stream()]
    r["doc"] = db.collection("runs").document(r["id"]).get().to_dict()
    r["brief"] = db.collection("briefs").document(r["id"]).get()
ids = {r["id"]: r["tier"] for r in runs.values()}

# 1 PREPARE only from 50 m; STOP always
prep = [a for r in runs.values() for a in r["alerts"] if a["stage"] == "PREPARE"]
stops = [a for r in runs.values() for a in r["alerts"] if a["stage"] == "STOP"]
check(
    "no PREPARE with jam_m < 50",
    prep and all(a["jam_m"] >= 50 for a in prep),
    f"{len(prep)} PREPARE, min jam {min(a['jam_m'] for a in prep)} m",
)
check(
    "STOP fires with jam_m < 50",
    any(a["jam_m"] < 50 for a in stops),
    f"{len(stops)} STOP, {sum(a['jam_m'] < 50 for a in stops)} under 50 m",
)
check("alerts are text only offline", all(a["audio_url"] is None for r in runs.values() for a in r["alerts"]))

# 2 + 6 brief timing; fire has no brief and no routing
crit, urg, fire = by_tier["critical"], by_tier["urgent"], by_tier["fire_with_trapped"]
b = crit["brief_at"]
check(
    "critical brief only once under way (junction passed or 500 m driven)",
    b
    and (b["passed"] or b["distance_m"] >= 500)
    and b["tick"] > 1
    and crit["brief"].exists
    and crit["brief"].to_dict()["model"] == "offline",
    str(b),
)
check(
    "no brief on the first tick",
    all(not (r["brief_at"] and r["brief_at"]["tick"] == 1) for r in runs.values()),
)
check(
    "no brief and no routing for fire",
    not fire["brief"].exists and not fire["doc"].get("brief_fired") and "routing" not in fire["doc"],
)

# 3 next_junction strictly monotonic per run
for r in runs.values():
    idx = [ORDER.index(j) for j in r["next"]]
    check(f"next_junction monotonic ({r['tier']})", idx == sorted(set(idx)), " > ".join(r["next"]))

# 4 scenario runs keep the corridor hospital
for r in (crit, urg):
    rt = r["doc"].get("routing") or {}
    check(
        f"routing recorded, not applied ({r['tier']})",
        rt.get("applied") is False
        and rt.get("reason") == "scenario run keeps corridor hospital"
        and r["doc"]["destination"]["name"] == C["hospital"]["name"],
        f"routing -> {rt.get('destination')}",
    )

# 5 platoon: critical and urgent on the same approach within 45 s share the j3 slot; the fire (other approach) goes first
j3 = [
    d.to_dict()
    for d in db.collection("audit").where(filter=FieldFilter("junction_id", "==", "blr_j3")).stream()
]
seqs = [
    {ids[s["run_id"]]: s["offset_s"] for s in a["sequence"] if s["run_id"] in ids}
    for a in j3
    if a.get("action") == "preempt_requested"
]
pair = [s for s in seqs if {"critical", "urgent"} <= set(s)]
check(
    "critical and urgent share a j3 slot",
    pair and all(s["critical"] == s["urgent"] for s in pair),
    str(pair[:2]),
)
check(
    "different approach gets its own slot",
    any("fire_with_trapped" in s and s["critical"] - s["fire_with_trapped"] == 12 for s in pair),
    str(pair[:2]),
)

# 7 report: actual_s from the first tick
for r in runs.values():
    want = r["ok"][-1] - r["ok"][0]
    check(
        f"actual_s from first tick ({r['tier']})",
        r["report"]["actual_s"] == want and r["doc"].get("first_tick_at"),
        f"{r['report']['actual_s']} s, want {want}",
    )

print(f"\n{sum(checks)}/{len(checks)} checks passed")
sys.exit(0 if all(checks) else 1)
