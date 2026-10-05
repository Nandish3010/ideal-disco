"""Cloud Run Job: log live Routes traffic spans per junction approach into BigQuery corridor.traffic_spans."""
import json, math, os, sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from google.cloud import bigquery

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
from leadtime import jam_metres

ROOT = Path(__file__).resolve().parent.parent
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "green-corridor-2026")
KEY = os.environ["MAPS_SERVER_KEY"]  # injected from Secret Manager corridor-maps-server-key
URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
MASK = "routes.polyline,routes.duration,routes.travelAdvisory.speedReadingIntervals"
TABLE = f"{PROJECT}.corridor.traffic_spans"
SCHEMA = [bigquery.SchemaField(n, t) for n, t in [
    ("junction_id", "STRING"), ("approach", "STRING"), ("ts", "TIMESTAMP"), ("jam_m", "FLOAT"),
    ("slow_m", "FLOAT"), ("routes_eta_s", "FLOAT"), ("corridor", "STRING")]]


def decode(s):  # Google encoded polyline -> [(lat, lng)]
    pts, i, lat, lng = [], 0, 0, 0
    while i < len(s):
        for axis in range(2):
            shift = res = 0
            while True:
                b = ord(s[i]) - 63; i += 1
                res |= (b & 31) << shift; shift += 5
                if b < 32: break
            d = ~(res >> 1) if res & 1 else res >> 1
            if axis == 0: lat += d
            else: lng += d
        pts.append((lat / 1e5, lng / 1e5))
    return pts


def metres(a, b):
    return math.hypot((b[0] - a[0]) * 111320, (b[1] - a[1]) * 111320 * math.cos(math.radians(a[0])))


def spans(route):
    pts = decode(route["polyline"]["encodedPolyline"])
    cum = [0.0]
    for a, b in zip(pts, pts[1:]): cum.append(cum[-1] + metres(a, b))
    ivs = route.get("travelAdvisory", {}).get("speedReadingIntervals", [])  # none -> NORMAL
    return [{"from_m": cum[iv.get("startPolylinePointIndex", 0)], "to_m": cum[iv.get("endPolylinePointIndex", 0)],
             "speed": iv.get("speed", "NORMAL")} for iv in ivs]


def main():
    bq = bigquery.Client(project=PROJECT, location="asia-south1")
    bq.create_dataset("corridor", exists_ok=True)
    bq.create_table(bigquery.Table(TABLE, schema=SCHEMA), exists_ok=True)
    rows, now = [], datetime.now(timezone.utc).isoformat()
    for f in sorted((ROOT / "data" / "corridors").glob("*.json")):
        c = json.loads(f.read_text())
        for j in c["junctions"]:
            for ap in j["approaches"]:
                lat, lng = ap["polyline"][0]
                body = {"origin": {"location": {"latLng": {"latitude": lat, "longitude": lng}}},
                        "destination": {"location": {"latLng": {"latitude": j["lat"], "longitude": j["lng"]}}},
                        "travelMode": "DRIVE", "routingPreference": "TRAFFIC_AWARE",
                        "extraComputations": ["TRAFFIC_ON_POLYLINE"]}
                r = httpx.post(URL, json=body, headers={"X-Goog-Api-Key": KEY, "X-Goog-FieldMask": MASK}, timeout=15)
                if r.status_code != 200:
                    print(f"routes {r.status_code} junction={c['id']}_{j['id']} approach={ap['id']}", file=sys.stderr)
                    continue  # skip the row; a gap in the log beats a fake zero
                route = r.json()["routes"][0]
                iv = spans(route)
                rows.append({"junction_id": f"{c['id']}_{j['id']}", "approach": ap["id"], "ts": now,
                             "jam_m": jam_metres(iv),
                             "slow_m": sum(i["to_m"] - i["from_m"] for i in iv if i["speed"] == "SLOW"),
                             "routes_eta_s": float(route["duration"].rstrip("s")), "corridor": c["id"]})
    errs = bq.insert_rows_json(TABLE, rows) if rows else []
    print(f"inserted={len(rows)} errors={errs}")
    if errs: sys.exit(1)


if __name__ == "__main__":
    main()
