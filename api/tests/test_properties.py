"""Property tests: the engines hold their invariants for any input, not only the examples in the unit tests."""

from hypothesis import given
from hypothesis import strategies as st

import acuity
import leadtime
import priority

SPEEDS = ["NORMAL", "SLOW", "TRAFFIC_JAM"]
metres = st.floats(min_value=0, max_value=5_000, allow_nan=False)


LENGTHS = st.lists(
    st.floats(min_value=1, max_value=900, allow_nan=False), max_size=12
)  # Routes gives no empty spans


def chain(lengths: list[float], speeds: list[str]) -> list[dict]:
    """Back-to-back intervals from 0 m with the given lengths."""
    ivs, at = [], 0.0
    for n, ln in enumerate(lengths):
        ivs.append({"from_m": at, "to_m": at + ln, "speed": speeds[n % len(speeds)]})
        at += ln
    return ivs


@st.composite
def route_intervals(draw: st.DrawFn) -> list[dict]:
    """Back-to-back speed intervals along a route, in any order."""
    ivs = chain(draw(LENGTHS), draw(st.lists(st.sampled_from(SPEEDS), min_size=1, max_size=12)))
    return draw(st.permutations(ivs))


@given(route_intervals())
def test_jam_metres_is_between_zero_and_the_route_length(ivs: list[dict]) -> None:
    jam = leadtime.jam_metres(ivs)
    assert 0 <= jam <= sum(i["to_m"] - i["from_m"] for i in ivs) + 1e-6


@given(route_intervals())
def test_jam_metres_ignores_the_order_the_intervals_arrive_in(ivs: list[dict]) -> None:
    assert leadtime.jam_metres(ivs) == leadtime.jam_metres(sorted(ivs, key=lambda i: i["from_m"]))


@given(route_intervals(), metres)
def test_a_normal_stretch_at_the_stop_line_means_no_queue(ivs: list[dict], length: float) -> None:
    end = max((i["to_m"] for i in ivs), default=0.0)
    ivs = [*ivs, {"from_m": end, "to_m": end + length + 1, "speed": "NORMAL"}]
    assert leadtime.jam_metres(ivs) == 0


@given(LENGTHS)
def test_a_queue_of_only_jam_is_its_whole_length(lengths: list[float]) -> None:
    assert abs(leadtime.jam_metres(chain(lengths, ["TRAFFIC_JAM"])) - sum(lengths)) < 1e-6


TIERS = list(priority.TIER_RANK) + ["mystery"]
VEHICLE_OF = {"fire_with_trapped": "fire", "fire": "fire", "police_with_incident": "police"}


@st.composite
def contenders(draw: st.DrawFn) -> list[dict]:
    out = []
    for n in range(draw(st.integers(0, 8))):
        tier = draw(st.sampled_from(TIERS))
        out.append(
            {
                "run_id": f"r{n}",
                "tier": tier,
                "vehicle_type": VEHICLE_OF.get(tier, "ambulance"),
                "eta_s": draw(st.floats(min_value=0, max_value=600, allow_nan=False)),
                "approach": draw(st.sampled_from([None, "N", "S", "E", "W"])),
            }
        )
    return out


def rank(c: dict) -> int:
    return priority.TIER_RANK.get(priority.key(c), len(priority.TIER_RANK))


@given(contenders())
def test_sequence_keeps_every_vehicle_in_tier_then_eta_order(cs: list[dict]) -> None:
    out = priority.sequence(cs)
    assert sorted(c["run_id"] for c in out) == sorted(c["run_id"] for c in cs)
    keys = [(rank(c), c["eta_s"]) for c in out]
    assert keys == sorted(keys)  # a higher tier is never behind a lower one; ties go to the earlier arrival


@given(contenders())
def test_each_new_green_slot_comes_a_gap_after_the_last(cs: list[dict]) -> None:
    """Slot leaders get offsets 0, GAP, 2 GAP... in priority order. A later vehicle may join an earlier slot (same
    approach, within PLATOON_S), so offsets along the list are not monotonic by design."""
    out = priority.sequence(cs)
    first_seen = list(dict.fromkeys(c["offset_s"] for c in out))
    assert first_seen == [i * priority.GAP_S for i in range(len(first_seen))]


@given(contenders())
def test_only_a_same_approach_platoon_shares_a_green(cs: list[dict]) -> None:
    out = priority.sequence(cs)
    leaders: dict[int, dict] = {}
    for c in out:
        lead = leaders.setdefault(c["offset_s"], c)  # the first vehicle in a slot is its leader
        if c is not lead:
            assert c["approach"] and c["approach"] == lead["approach"]
            assert abs(c["eta_s"] - lead["eta_s"]) <= priority.PLATOON_S


@given(contenders())
def test_sequence_does_not_change_its_input(cs: list[dict]) -> None:
    before = [dict(c) for c in cs]
    priority.sequence(cs)
    assert cs == before


COMPLAINTS = st.sampled_from(
    ["", "headache", "fracture", "breathing difficulty", "fall", "Chest Pain", "stroke signs"]
)
vital = st.one_of(st.none(), st.integers(0, 250))
fields = st.fixed_dictionaries(
    {},
    optional={
        "complaint": COMPLAINTS,
        "conscious": st.one_of(st.none(), st.booleans()),
        "breathing": st.one_of(st.none(), st.booleans()),
        "trapped_persons": st.one_of(st.none(), st.integers(0, 5)),
        "vitals": st.fixed_dictionaries(
            {}, optional={"sbp": vital, "dbp": vital, "hr": vital, "spo2": vital, "rr": vital}
        ),
    },
)


@given(fields)
def test_a_critical_sign_is_critical_whatever_else_is_reported(f: dict) -> None:
    critical = (
        f.get("conscious") is False
        or f.get("breathing") is False
        or (f.get("vitals", {}).get("sbp") is not None and f["vitals"]["sbp"] < 90)
        or (f.get("vitals", {}).get("spo2") is not None and f["vitals"]["spo2"] < 90)
        or any(c in f.get("complaint", "").lower() for c in acuity.CRITICAL_COMPLAINTS)
        or (f.get("trapped_persons") or 0) > 0
    )
    got = acuity.tier(f, "ambulance")
    assert got in {"critical", "urgent", "stable"}
    assert (got == "critical") == critical


@given(fields)
def test_adding_a_critical_sign_never_lowers_the_tier(f: dict) -> None:
    order = {"stable": 0, "urgent": 1, "critical": 2}
    worse = {**f, "conscious": False}
    assert order[acuity.tier(worse, "ambulance")] == 2 >= order[acuity.tier(f, "ambulance")]
