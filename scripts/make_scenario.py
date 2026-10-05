"""Generate data/scenarios/blr-two-vehicles.json from data/corridors/blr.json.

Ticks are interpolated along the corridor's approach polylines, so rerun this after the corridor file changes:
    python3 scripts/make_scenario.py
Ambulance KA01AB1234 (critical) runs all 5 junctions to the hospital; fire engine KA01FE5678
(fire_with_trapped) comes in on j3's cross approach and reaches the stop line ~3 s ahead of it; a second
ambulance KA01AB4321 (urgent) is the first one's trace 40 s later (platoon on the j3 corridor approach).
Span intervals use route order (stop line = largest to_m), like api/leadtime.py and the traffic logger.
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
C = json.loads((ROOT / "data/corridors/blr.json").read_text())
J = {j["id"]: j for j in C["junctions"]}
DT = 5  # seconds between ticks


def dist(a, b):  # equirectangular, fine at junction scale
    return math.hypot((b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2)), b[0] - a[0]) * math.radians(1) * 6371000


def appr(j, aid):
    return next(a for a in J[j]["approaches"] if a["id"] == aid)["polyline"]


def tail(poly, m):
    """Last m metres of a far->junction polyline."""
    out, acc = [poly[-1]], 0.0
    for i in range(len(poly) - 1, 0, -1):
        d = dist(poly[i - 1], poly[i])
        if acc + d >= m:
            f = (m - acc) / d
            out.insert(0, [poly[i][0] + (poly[i - 1][0] - poly[i][0]) * f, poly[i][1] + (poly[i - 1][1] - poly[i][1]) * f])
            return out
        acc += d
        out.insert(0, poly[i - 1])
    return out


def build(parts):
    pts, stops = [], {}
    for p, stop in parts:
        for q in p:
            if not pts or dist(pts[-1], q) > 0.5:
                pts.append(q)
        if stop:
            stops[stop] = sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    cum = [0.0]
    for i in range(len(pts) - 1):
        cum.append(cum[-1] + dist(pts[i], pts[i + 1]))
    return pts, cum, stops


def at(path, s):
    pts, cum, _ = path
    s = min(max(s, 0), cum[-1])
    i = next((k for k, c in enumerate(cum) if c >= s), len(cum) - 1)
    i = max(i, 1)
    f = (s - cum[i - 1]) / ((cum[i] - cum[i - 1]) or 1)
    return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * f, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f]


def rnd(x, n):  # round half up, like the JS this was prototyped in
    return math.floor(x * 10**n + 0.5) / 10**n


def speed_at(path, s, jams):
    """m/s: 8-14, slower near stop lines and through queues (an emergency vehicle filters through them)."""
    v = min(14, 13 + 1.2 * math.sin(s / 140))
    for j, d in path[2].items():
        if d - 60 < s < d + 20:
            v = min(v, 10.5)
        if j in jams and d - jams[j] < s <= d:
            v = min(v, 8.4 + 0.5 * math.sin(s / 20) if j == "j3" else 10)
    return rnd(v, 1)


def drive(path, s0, jams, max_ticks):
    ticks, s = [], s0
    for k in range(max_ticks):
        if s > path[1][-1]:
            break
        v = speed_at(path, s, jams)
        lat, lng = at(path, s)
        ticks.append({"t": k * DT, "lat": rnd(lat, 5), "lng": rnd(lng, 5), "speed_mps": v, "_s": s})
        s += v * DT
    return ticks


def time_at(ticks, s):
    i = next((k for k, t in enumerate(ticks) if t["_s"] >= s), 0)
    if i <= 0:
        return 0.0
    return ticks[i - 1]["t"] + DT * (s - ticks[i - 1]["_s"]) / (ticks[i]["_s"] - ticks[i - 1]["_s"])


hosp = [C["hospital"]["lat"], C["hospital"]["lng"]]
main = build([
    (tail(appr("j1", "SE"), 250), "j1"),
    (tail(appr("j2", "SE"), 250), "j2"),
    (appr("j3", "SE"), "j3"),
    (tail(appr("j4", "E"), 250), "j4"),
    (tail(appr("j5", "E"), 250), "j5"),
    ([hosp], None),
])
JAMS = {"j3": 500, "j4": 100}
amb = drive(main, 0, JAMS, 200)
amb_j3 = time_at(amb, main[2]["j3"])

# platoon: the second ambulance is the first one's trace from tick a, shifted so it is 40 s behind, 30 ticks
a = max(0, int(amb_j3 // DT) - 12)
amb2 = [{**k, "t": i * DT} for i, k in enumerate(amb[a:a + 30])]
amb2_start = round(a * DT + 40)

# fire engine: last 330 m of j3's cross approach, then on toward j4; at the j3 stop line ~3 s before the ambulance
fire_path = build([(tail(appr("j3", "NE"), 330), "j3"), ([tail(appr("j4", "E"), 250)[0]], None)])
fire = drive(fire_path, 0, {}, 12)
fire_start = round(amb_j3 - 3 - time_at(fire, fire_path[2]["j3"]))


def stamp(ts):
    return f"2026-10-05T09:{ts}+05:30"


def full(jam, slow=0):
    iv = [{"from_m": 0, "to_m": 600 - jam - slow, "speed": "NORMAL"}]
    if slow:
        iv.append({"from_m": 600 - jam - slow, "to_m": 600 - jam, "speed": "SLOW"})
    if jam:
        iv.append({"from_m": 600 - jam, "to_m": 600, "speed": "TRAFFIC_JAM"})
    return iv


def snaps(items):
    return [{"ts": stamp(ts), "intervals": iv} for ts, iv in items]


def j3snap(ts, jam):  # the 500 m tail is on the corridor (SE) approach only
    return {"ts": stamp(ts), "approach": "SE", "intervals": full(jam, 40)}


def clean(ticks):
    return [{k: v for k, v in t.items() if k != "_s"} for t in ticks]


out = {
    "corridor": "blr",
    "seed": 20261005,
    "baseline_cycle": {
        "red_fraction": 0.5,
        "note": "Today lane: each junction runs a fixed signal cycle (cycle_s from the corridor file, first red_fraction of it red). A vehicle is assumed to arrive at a uniformly random but seeded phase of that cycle, waits out the remaining red, then the queue ahead drains at 2.0 m/s (jam_m / 2.0). Spans are in route order: the stop line is the largest to_m. Simulated estimate on recorded traffic, not a field measurement.",
    },
    "vehicles": [
        {"run_id": "run-amb-1", "plate": "KA01AB1234", "type": "ambulance", "tier": "critical", "start_offset_s": 0,
         "approaches": {"j1": "SE", "j2": "SE", "j3": "SE", "j4": "E", "j5": "E"}, "ticks": clean(amb)},
        {"run_id": "run-fire-1", "plate": "KA01FE5678", "type": "fire", "tier": "fire_with_trapped", "start_offset_s": fire_start,
         "approaches": {"j3": "NE"}, "ticks": clean(fire)},
        {"run_id": "run-amb-2", "plate": "KA01AB4321", "type": "ambulance", "tier": "urgent", "start_offset_s": amb2_start,
         "approaches": {"j3": "SE", "j4": "E", "j5": "E"}, "ticks": clean(amb2)},
    ],
    "recorded_spans": {
        "blr_j1": snaps([("00:00", full(0, 60))]),
        "blr_j2": snaps([("00:00", full(0))]),
        "blr_j3": [j3snap("00:00", 380), j3snap("01:30", 500), j3snap("04:00", 500)],
        "blr_j4": snaps([("00:00", full(100)), ("02:00", full(100))]),
        "blr_j5": snaps([("00:00", full(0, 40))]),
    },
}


def num(x):
    return str(int(x)) if isinstance(x, float) and x == int(x) else json.dumps(x)


# one tick per line keeps the file readable and diffable: dump with placeholders, then splice the tick blocks in
blocks = {}
for n, v in enumerate(out["vehicles"]):
    blocks[f"@@{n}@@"] = "[\n" + ",\n".join(
        "        {" + ", ".join(f'"{k}": {num(x)}' for k, x in t.items()) + "}" for t in v["ticks"]) + "\n      ]"
    v["ticks"] = f"@@{n}@@"
text = json.dumps(out, indent=2)
for k, b in blocks.items():
    text = text.replace(f'"{k}"', b)
(ROOT / "data/scenarios/blr-two-vehicles.json").write_text(text + "\n")
json.loads(text)  # fail loudly if the layout trick ever breaks the JSON
print(f"ambulance {len(amb)} ticks, j3 at {amb_j3:.0f} s; fire +{fire_start} s ({len(fire)} ticks); amb2 +{amb2_start} s ({len(amb2)} ticks)")
