"""Google Routes computeRoutes with live traffic. Cached per key, shared across instances through Firestore
(`route_cache/{run_id}`) with a small in-memory layer in front; on failure reuse recent spans, else NORMAL."""

import os
import time
from datetime import UTC, datetime, timedelta

import httpx

from corridor import distance_m
from firestore_client import db
from gemini import log

URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
MASK = "routes.polyline.encodedPolyline,routes.duration,routes.travelAdvisory.speedReadingIntervals"
STEPS_MASK = ",routes.legs.steps.navigationInstruction,routes.legs.steps.startLocation"  # exit manoeuvre
REUSE_S = 60  # on 429/5xx/timeout, spans this old are still better than nothing
CACHE_DOC_TTL = timedelta(days=1)  # expires_at on route_cache docs, for a Firestore TTL policy to sweep
_cache: dict = {}  # (run_id, what) -> (monotonic ts, result): this instance's copy, in front of Firestore


def _doc(key):
    return db.collection("route_cache").document(str(key[0] if isinstance(key, tuple) else key))


def _read_shared(key, ctx) -> tuple[float, dict] | None:
    """(age_s, result) from route_cache/{run_id}, or None (no doc, or Firestore down: the cache is never load-bearing)."""
    try:
        d = _doc(key).get().to_dict()
        if not d:
            return None
        flat = d["result"]["polyline_points"]  # Firestore has no nested arrays: stored flat
        res = {**d["result"], "polyline_points": list(zip(flat[::2], flat[1::2], strict=True))}
        return max((datetime.now(UTC) - d["fetched_at"]).total_seconds(), 0.0), res
    except Exception as e:
        log(event="route_cache_error", op="read", error=type(e).__name__, **ctx)
        return None


def _write_shared(key, res, ctx) -> None:
    now = datetime.now(UTC)
    flat = [c for p in res["polyline_points"] for c in p]
    try:
        _doc(key).set(
            {"result": {**res, "polyline_points": flat}, "fetched_at": now, "expires_at": now + CACHE_DOC_TTL}
        )
    except Exception as e:
        log(event="route_cache_error", op="write", error=type(e).__name__, **ctx)


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


def traffic_to_point(origin, dest, key=None, ttl=20, steps=False, alt=0, **ctx) -> dict:
    """origin, dest = (lat, lng) -> {polyline_points, duration_s, intervals:[{from_m,to_m,speed}], steps, age_s, stale}.
    Result is cached under `key` for `ttl` s (throttle): in this instance's memory, else from the shared Firestore doc
    another instance wrote. On error: cached result <= 60 s old, else no spans (NORMAL), duration_s None, stale True.
    alt=1 asks for alternatives too and returns the first one (a re-planned route); with fewer routes than that it fails
    like any other error. Give it its own cache key: the shared doc is per run id. ctx (run_id, junction_id) goes on every
    log line."""
    now, hit = time.monotonic(), None
    if key is not None:
        mem = _cache.get(key)
        hit = (now - mem[0], mem[1]) if mem else None
        if hit is None or hit[0] >= ttl:  # memory can't serve it: another instance may have fetched since
            shared = _read_shared(key, ctx)
            if shared and (hit is None or shared[0] < hit[0]):
                hit = shared
                _cache[key] = (now - shared[0], shared[1])
    if hit and hit[0] < ttl:
        return {**hit[1], "age_s": hit[0], "stale": False}

    def ll(p):
        return {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}

    body = {
        "origin": ll(origin),
        "destination": ll(dest),
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "extraComputations": ["TRAFFIC_ON_POLYLINE"],
        **({"computeAlternativeRoutes": True} if alt else {}),
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
        res = parse(r.json()["routes"][alt])
    except (httpx.HTTPError, LookupError) as e:  # timeout, 429, 5xx, ZERO_RESULTS
        log(
            event="routes_error",
            error=type(e).__name__,
            status=getattr(getattr(e, "response", None), "status_code", None),
            **ctx,
        )
        if hit and hit[0] <= REUSE_S:
            return {**hit[1], "age_s": hit[0], "stale": True}
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
        _write_shared(key, res, ctx)
    return {**res, "age_s": 0, "stale": False}
