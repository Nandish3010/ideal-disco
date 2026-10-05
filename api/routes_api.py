"""Google Routes computeRoutes with live traffic. Cached per key; on failure reuse recent spans, else NORMAL."""

import os
import time

import httpx

from corridor import distance_m
from gemini import log

URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
MASK = "routes.polyline.encodedPolyline,routes.duration,routes.travelAdvisory.speedReadingIntervals"
STEPS_MASK = ",routes.legs.steps.navigationInstruction,routes.legs.steps.startLocation"  # exit manoeuvre
REUSE_S = 60  # on 429/5xx/timeout, spans this old are still better than nothing
_cache: dict = {}  # (run_id, what) -> (monotonic ts, result); ponytail: per-instance memory, Cloud Run restarts just refetch


def decode(s):  # Google encoded polyline -> [(lat, lng)]
    pts, i, lat, lng = [], 0, 0, 0
    while i < len(s):
        for axis in range(2):
            shift = res = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                res |= (b & 31) << shift
                shift += 5
                if b < 32:
                    break
            d = ~(res >> 1) if res & 1 else res >> 1
            if axis == 0:
                lat += d
            else:
                lng += d
        pts.append((lat / 1e5, lng / 1e5))
    return pts


def parse(route) -> dict:
    pts = decode(route["polyline"]["encodedPolyline"])
    cum = [0.0]
    for a, b in zip(pts, pts[1:], strict=False):
        cum.append(cum[-1] + distance_m(a, b))
    ivs = route.get("travelAdvisory", {}).get("speedReadingIntervals", [])  # none -> NORMAL
    steps = [
        {
            "lat": s["startLocation"]["latLng"]["latitude"],
            "lng": s["startLocation"]["latLng"]["longitude"],
            "maneuver": s.get("navigationInstruction", {}).get("maneuver", ""),
        }
        for leg in route.get("legs", [])
        for s in leg.get("steps", [])
        if "startLocation" in s
    ]
    return {
        "polyline_points": pts,
        "duration_s": float(route["duration"].rstrip("s")),
        "steps": steps,
        "intervals": [
            {
                "from_m": cum[iv.get("startPolylinePointIndex", 0)],
                "to_m": cum[iv.get("endPolylinePointIndex", 0)],
                "speed": iv.get("speed", "NORMAL"),
            }
            for iv in ivs
        ],
    }


def exit_move(steps, junction) -> str:
    """left | straight | right at a junction (lat, lng): the manoeuvre of the step that starts there; no step means straight."""
    near = min(steps, key=lambda s: distance_m((s["lat"], s["lng"]), junction), default=None)
    if near is None or distance_m((near["lat"], near["lng"]), junction) > 80:
        return "straight"
    m = near["maneuver"]
    return "left" if "LEFT" in m else "right" if "RIGHT" in m else "straight"


def traffic_to_point(origin, dest, key=None, ttl=20, steps=False, **ctx) -> dict:
    """origin, dest = (lat, lng) -> {polyline_points, duration_s, intervals:[{from_m,to_m,speed}], steps, age_s, stale}.
    Result is cached under `key` for `ttl` s (throttle). On error: cached result <= 60 s old, else no spans (NORMAL),
    duration_s None, stale True. ctx (run_id, junction_id) goes on every log line."""
    now, hit = time.monotonic(), (_cache.get(key) if key is not None else None)
    if hit and now - hit[0] < ttl:
        return {**hit[1], "age_s": now - hit[0], "stale": False}

    def ll(p):
        return {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}

    body = {
        "origin": ll(origin),
        "destination": ll(dest),
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "extraComputations": ["TRAFFIC_ON_POLYLINE"],
    }
    try:
        r = httpx.post(
            URL,
            json=body,
            timeout=4,
            headers={
                "X-Goog-Api-Key": os.environ.get("MAPS_SERVER_KEY", "").strip(),
                "X-Goog-FieldMask": MASK + (STEPS_MASK if steps else ""),
            },
        )
        r.raise_for_status()
        res = parse(r.json()["routes"][0])
    except (httpx.HTTPError, LookupError) as e:  # timeout, 429, 5xx, ZERO_RESULTS
        log(
            event="routes_error",
            error=type(e).__name__,
            status=getattr(getattr(e, "response", None), "status_code", None),
            **ctx,
        )
        if hit and now - hit[0] <= REUSE_S:
            return {**hit[1], "age_s": now - hit[0], "stale": True}
        log(event="traffic_stale", **ctx)
        return {
            "polyline_points": [],
            "duration_s": None,
            "intervals": [],
            "steps": [],
            "age_s": 0,
            "stale": True,
        }
    if key is not None:
        _cache[key] = (now, res)
    return {**res, "age_s": 0, "stale": False}
