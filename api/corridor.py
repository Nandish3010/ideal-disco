"""Corridor config and route geometry. Corridors and scenarios load once at startup."""

import json
import math
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# api/data/ is a copy made by the deploy build; locally the repo's data/ is used
DATA = next(p for p in (_HERE / "data", _HERE.parent / "data") if p.exists())
CORRIDORS = {
    c["id"]: c for c in (json.loads(f.read_text()) for f in sorted((DATA / "corridors").glob("*.json")))
}
SCENARIOS = {f.stem: json.loads(f.read_text()) for f in (DATA / "scenarios").glob("*.json")}

MATCH_M = 100  # a junction counts as "on the route" if the polyline passes within this (junction coords are hand-placed)


def _xy(p, a):  # metres (east, north) of a relative to p; flat earth is fine at city scale
    return (a[1] - p[1]) * 111320 * math.cos(math.radians(p[0])), (a[0] - p[0]) * 111320


def distance_m(a, b) -> float:
    return math.hypot(*_xy(a, b))


def bearing(a, b) -> float:
    x, y = _xy(a, b)
    return math.degrees(math.atan2(x, y)) % 360


def angle_diff(a, b) -> float:
    return abs((a - b + 180) % 360 - 180)


def locate(points, p):
    """Nearest point of a polyline to p -> (metres along the polyline, metres off it)."""
    best, cum = (math.inf, 0.0), 0.0
    for a, b in zip(points, points[1:], strict=False):
        ax, ay = _xy(p, a)
        bx, by = _xy(p, b)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2)) if seg2 else 0.0
        off, length = math.hypot(ax + t * dx, ay + t * dy), math.sqrt(seg2)
        if off < best[0]:
            best = (off, cum + t * length)
        cum += length
    return best[1], best[0]


def heading_at(points, along_m) -> float:
    """Direction of travel on the polyline at `along_m` metres from its start."""
    cum = 0.0
    for a, b in zip(points, points[1:], strict=False):
        cum += distance_m(a, b)
        if cum >= along_m:
            return bearing(a, b)
    return bearing(points[-2], points[-1])


def junctions_ahead(corridor, lat, lng, heading, route_points):
    """Every junction still ahead of the vehicle, nearest first -> [(junction, approach)].
    route_points = Routes polyline [(lat, lng)]: ahead means further along it than the vehicle. Without a route (scenario
    replay) ahead means within 90 deg of `heading`, ordered by straight-line distance. The approach is the one whose bearing
    is closest to the direction of travel into the junction (route direction there; without a route the vehicle heading
    when close, else the straight-line bearing). Returned junctions are copies carrying `doc_id` (e.g. blr_j3) and
    `ahead_m`; the approach carries `bearing_err` (deg; > 45 means no approach really fits)."""
    me, found = (lat, lng), []
    v_along = locate(route_points, me)[0] if route_points else 0
    for j in corridor["junctions"]:
        c = (j["lat"], j["lng"])
        if route_points:
            along, off = locate(route_points, c)
            ahead = along - v_along
            if off > MATCH_M or ahead < -15:  # off the route, or already passed (15 m GPS slack)
                continue
            into = heading_at(route_points, max(along - 5, 0))
        else:
            ahead, to_j = distance_m(me, c), bearing(me, c)
            if heading is not None and angle_diff(to_j, heading) > 90:
                continue
            into = heading if heading is not None and ahead < 100 else to_j
        ap = min(
            ({**a, "bearing_err": angle_diff(a["bearing"], into)} for a in j["approaches"]),
            key=lambda a: a["bearing_err"],
        )
        found.append(
            (max(ahead, 0), {**j, "doc_id": f"{corridor['id']}_{j['id']}", "ahead_m": max(ahead, 0)}, ap)
        )
    return [(j, ap) for _, j, ap in sorted(found, key=lambda f: f[0])]


def next_junction(corridor, lat, lng, heading, route_points):
    """First junction ahead -> (junction, approach); (None, None) when none is left."""
    ahead = junctions_ahead(corridor, lat, lng, heading, route_points)
    return ahead[0] if ahead else (None, None)
