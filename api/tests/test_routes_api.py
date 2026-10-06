"""Routes parsing and the cache/failure rules, with httpx stubbed."""

import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import routes_api
from fakefs import FakeFirestore

GOOGLE_EXAMPLE = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
ROUTE = {
    "polyline": {"encodedPolyline": GOOGLE_EXAMPLE},
    "duration": "95s",
    "travelAdvisory": {
        "speedReadingIntervals": [
            {"endPolylinePointIndex": 1, "speed": "NORMAL"},
            {"startPolylinePointIndex": 1, "endPolylinePointIndex": 2, "speed": "TRAFFIC_JAM"},
        ]
    },
    "legs": [
        {
            "steps": [
                {
                    "startLocation": {"latLng": {"latitude": 40.7, "longitude": -120.95}},
                    "navigationInstruction": {"maneuver": "TURN_LEFT"},
                }
            ]
        }
    ],
}
A, B = (12.9, 77.6), (12.91, 77.61)


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_api, "_cache", {})
    monkeypatch.setenv("MAPS_SERVER_KEY", " k \n")


def stub_post(monkeypatch: pytest.MonkeyPatch, result: Any) -> list[dict]:
    calls: list[dict] = []

    def post(url: str, json: dict, timeout: float, headers: dict) -> Any:
        calls.append({"url": url, "headers": headers, "body": json})
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(routes_api.httpx, "post", post)
    return calls


def ok(route: dict = ROUTE) -> Any:
    return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"routes": [route]})


def test_decode_google_reference_polyline() -> None:
    assert routes_api.decode(GOOGLE_EXAMPLE) == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_parse() -> None:
    p = routes_api.parse(ROUTE)
    assert p["duration_s"] == 95
    assert (p["intervals"][0]["from_m"], p["intervals"][1]["speed"]) == (0, "TRAFFIC_JAM")
    assert p["intervals"][0]["to_m"] == p["intervals"][1]["from_m"] > 200_000
    assert p["steps"] == [{"lat": 40.7, "lng": -120.95, "maneuver": "TURN_LEFT"}]


def test_exit_move() -> None:
    steps = routes_api.parse(ROUTE)["steps"]
    assert routes_api.exit_move(steps, (40.7, -120.95)) == "left"
    assert routes_api.exit_move(steps, (12.0, 77.0)) == "straight"  # no step within 80 m
    assert routes_api.exit_move([], (0, 0)) == "straight"
    right = [{"lat": 1.0, "lng": 1.0, "maneuver": "TURN_SLIGHT_RIGHT"}]
    assert routes_api.exit_move(right, (1.0, 1.0)) == "right"


def test_success_sends_the_stripped_key_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = stub_post(monkeypatch, ok())
    out = routes_api.traffic_to_point(A, B, key="k1", steps=True, run_id="r")
    assert out["stale"] is False and out["duration_s"] == 95
    assert calls[0]["headers"]["X-Goog-Api-Key"] == "k"  # no whitespace from the secret
    assert calls[0]["headers"]["X-Goog-FieldMask"].endswith(routes_api.STEPS_MASK)
    again = routes_api.traffic_to_point(A, B, key="k1")  # inside the 20 s throttle: no second call
    assert len(calls) == 1 and again["stale"] is False and again["intervals"] == out["intervals"]


def test_alt_asks_for_alternatives_and_takes_the_first_one(monkeypatch: pytest.MonkeyPatch) -> None:
    second = {**ROUTE, "duration": "140s"}
    calls = stub_post(
        monkeypatch,
        SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"routes": [ROUTE, second]}),
    )
    assert (
        routes_api.traffic_to_point(A, B)["duration_s"] == 95
    )  # the default: the best route, no alternatives asked
    assert "computeAlternativeRoutes" not in calls[0]["body"]
    assert routes_api.traffic_to_point(A, B, alt=1)["duration_s"] == 140
    assert calls[1]["body"]["computeAlternativeRoutes"] is True
    stub_post(monkeypatch, ok())  # only one route came back: a failure like any other
    out = routes_api.traffic_to_point(A, B, alt=1)
    assert out["duration_s"] is None and out["stale"] is True


@pytest.mark.parametrize("failure", [httpx.ConnectTimeout("t"), httpx.HTTPError("5xx"), ok({})])
def test_failure_without_cache_is_normal_and_stale(monkeypatch: pytest.MonkeyPatch, failure: Any) -> None:
    stub_post(monkeypatch, failure)
    out = routes_api.traffic_to_point(A, B, key="k", run_id="r", junction_id="j")
    assert out["intervals"] == [] and out["duration_s"] is None and out["stale"] is True


def test_failure_reuses_recent_spans_but_not_old_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_post(monkeypatch, httpx.ConnectTimeout("t"))
    parsed = routes_api.parse(ROUTE)
    routes_api._cache["k"] = (
        time.monotonic() - 40,
        parsed,
    )  # past the throttle, inside the 60 s reuse window
    out = routes_api.traffic_to_point(A, B, key="k")
    assert out["intervals"] == parsed["intervals"] and out["stale"] is True and out["age_s"] >= 40
    routes_api._cache["k"] = (time.monotonic() - 90, parsed)
    assert routes_api.traffic_to_point(A, B, key="k")["intervals"] == []


KEY = ("run-1", "route")


def test_a_fetch_is_stored_in_the_shared_doc_for_the_run(
    db: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_post(monkeypatch, ok())
    routes_api.traffic_to_point(A, B, key=KEY, run_id="run-1")
    doc = db.docs["route_cache/run-1"]
    assert (
        doc["result"]["duration_s"] == 95 and len(doc["result"]["polyline_points"]) == 6
    )  # flat: no nested arrays
    assert abs((datetime.now(UTC) - doc["fetched_at"]).total_seconds()) < 5
    assert doc["expires_at"] > doc["fetched_at"]  # the field a Firestore TTL policy deletes by


def test_a_fresh_instance_reuses_the_shared_doc_instead_of_calling_routes(
    db: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = stub_post(monkeypatch, ok())
    first = routes_api.traffic_to_point(A, B, key=KEY, run_id="run-1")
    monkeypatch.setattr(
        routes_api, "_cache", {}
    )  # another instance, or this one after a restart: empty memory
    again = routes_api.traffic_to_point(A, B, key=KEY, run_id="run-1")
    assert len(calls) == 1 and again["stale"] is False
    assert again["intervals"] == first["intervals"] and again["polyline_points"] == first["polyline_points"]
    assert 0 <= again["age_s"] < 5
    assert KEY in routes_api._cache  # and keeps it in memory from then on


def test_a_shared_doc_older_than_the_ttl_is_refetched(
    db: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = stub_post(monkeypatch, ok())
    routes_api.traffic_to_point(A, B, key=KEY)
    db.docs["route_cache/run-1"]["fetched_at"] = datetime.now(UTC) - timedelta(seconds=25)
    monkeypatch.setattr(routes_api, "_cache", {})
    routes_api.traffic_to_point(A, B, key=KEY)
    assert len(calls) == 2


def test_an_old_shared_doc_still_serves_when_routes_is_down(
    db: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_post(monkeypatch, ok())
    routes_api.traffic_to_point(A, B, key=KEY)
    db.docs["route_cache/run-1"]["fetched_at"] = datetime.now(UTC) - timedelta(seconds=40)
    monkeypatch.setattr(routes_api, "_cache", {})
    stub_post(monkeypatch, httpx.ConnectTimeout("t"))
    out = routes_api.traffic_to_point(A, B, key=KEY)
    assert out["stale"] is True and out["duration_s"] == 95


def test_firestore_errors_never_break_a_route_call(monkeypatch: pytest.MonkeyPatch) -> None:
    class Down:
        def collection(self, name: str) -> Any:
            raise RuntimeError("firestore down")

    monkeypatch.setattr(routes_api, "db", Down())
    stub_post(monkeypatch, ok())
    out = routes_api.traffic_to_point(A, B, key=KEY)
    assert out["stale"] is False and out["duration_s"] == 95
    assert routes_api.traffic_to_point(A, B, key=KEY)["stale"] is False  # the memory layer still works


def test_no_key_means_no_shared_doc(db: FakeFirestore, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_post(monkeypatch, ok())
    routes_api.traffic_to_point(A, B)
    assert not any(k.startswith("route_cache/") for k in db.docs)
