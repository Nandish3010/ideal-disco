import math

import pytest

from corridor import (
    CORRIDORS,
    SCENARIOS,
    angle_diff,
    bearing,
    distance_m,
    heading_at,
    junctions_ahead,
    locate,
    next_junction,
)

BLR = CORRIDORS["blr"]
J1, J2 = BLR["junctions"][0], BLR["junctions"][1]
START: tuple[float, float] = (
    J1["approaches"][0]["polyline"][0][0],
    J1["approaches"][0]["polyline"][0][1],
)  # 600 m out on j1's E approach
ROUTE = [START, (J1["lat"], J1["lng"]), (J2["lat"], J2["lng"])]
BETWEEN = ((J1["lat"] + J2["lat"]) / 2, (J1["lng"] + J2["lng"]) / 2)


def test_configs_load() -> None:
    assert {"blr", "hyd"} <= set(CORRIDORS)
    assert "blr-two-vehicles" in SCENARIOS


def test_geometry_basics() -> None:
    assert distance_m((12.0, 77.0), (12.001, 77.0)) == pytest.approx(111.32, abs=0.1)
    assert round(bearing((12, 77), (12.01, 77))) == 0
    assert round(bearing((12, 77), (12, 77.01))) == 90
    assert angle_diff(350, 10) == 20
    assert angle_diff(10, 350) == 20


def test_locate_and_heading_on_a_polyline() -> None:
    along, off = locate(ROUTE, (J1["lat"], J1["lng"]))
    assert off < 1 and along == pytest.approx(distance_m(START, (J1["lat"], J1["lng"])), abs=2)
    assert locate(ROUTE, (START[0], START[1] + 0.002))[1] > 150
    assert heading_at(ROUTE, 10) == pytest.approx(bearing(ROUTE[0], ROUTE[1]))
    assert heading_at(ROUTE, 1e9) == pytest.approx(bearing(ROUTE[1], ROUTE[2]))  # past the end: last segment


def test_next_junction_follows_the_route() -> None:
    j, ap = next_junction(BLR, *START, None, ROUTE)
    assert (j["id"], ap["id"], j["doc_id"]) == ("j1", "E", "blr_j1")
    assert 400 < j["ahead_m"] < 700


def test_passed_junctions_are_excluded() -> None:
    assert [j["id"] for j, _ in junctions_ahead(BLR, *START, None, ROUTE)] == ["j1", "j2"]
    assert [j["id"] for j, _ in junctions_ahead(BLR, *BETWEEN, None, ROUTE)] == ["j2"]
    assert next_junction(BLR, *BETWEEN, None, ROUTE)[0]["doc_id"] == "blr_j2"


def test_off_route_junctions_are_skipped() -> None:
    """A junction more than MATCH_M from the polyline is not on the route at all."""
    j5 = BLR["junctions"][-1]
    west = (j5["lat"], j5["lng"] - 0.01)
    assert next_junction(BLR, *west, None, [west, (west[0], west[1] - 0.01)]) == (None, None)


def test_without_a_route_heading_decides() -> None:
    assert next_junction(BLR, *START, 330, None)[0]["id"] == "j1"
    assert next_junction(BLR, *START, 150, None)[0] is None  # everything is behind


def test_approach_follows_route_direction_not_heading() -> None:
    assert next_junction(BLR, *START, 90, ROUTE)[1]["id"] == "E"


@pytest.mark.parametrize("junction", BLR["junctions"], ids=lambda j: j["id"])
def test_approach_by_bearing(junction: dict) -> None:
    """Heading into the junction along an approach's bearing from 50 m out selects that approach."""
    for ap in junction["approaches"]:
        rad = math.radians(ap["bearing"])
        lat = junction["lat"] - 50 * math.cos(rad) / 111320
        lng = junction["lng"] - 50 * math.sin(rad) / (111320 * math.cos(math.radians(junction["lat"])))
        found = {j["id"]: a for j, a in junctions_ahead(BLR, lat, lng, ap["bearing"], None)}
        assert found[junction["id"]]["id"] == ap["id"]
        assert found[junction["id"]]["bearing_err"] < 1


def test_nearest_junction_first() -> None:
    ahead = junctions_ahead(BLR, *START, None, ROUTE)
    assert [j["ahead_m"] for j, _ in ahead] == sorted(j["ahead_m"] for j, _ in ahead)
