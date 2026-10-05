"""Deterministic lead-time engine: how early to alert the cop for the queue that is actually there."""


def jam_metres(intervals: list[dict]) -> float:
    """intervals: [{from_m, to_m, speed}] along the approach, stop line at the largest to_m.
    Walk back from the stop line: TRAFFIC_JAM full + SLOW x 0.5, stop at the first NORMAL."""
    total = 0.0
    for iv in sorted(intervals, key=lambda i: i["to_m"], reverse=True):
        length = iv["to_m"] - iv["from_m"]
        if iv["speed"] == "TRAFFIC_JAM":
            total += length
        elif iv["speed"] == "SLOW":
            total += 0.5 * length
        else:
            break
    return total


JAM_LOOKBACK_M = 600  # how far back along the route from a stop line the queue is read


def slice_intervals(intervals: list[dict], lo_m: float, hi_m: float) -> list[dict]:
    """Speed intervals of a whole route ([{from_m, to_m, speed}], metres from its start) clipped to the window
    [lo_m, hi_m] with the stop line at hi_m: the input jam_metres reads for that junction. Intervals outside are dropped."""
    return [
        {**iv, "from_m": max(iv["from_m"], lo_m), "to_m": min(iv["to_m"], hi_m)}
        for iv in intervals
        if iv["to_m"] > lo_m and iv["from_m"] < hi_m
    ]


# ponytail: constant clearance rate, BQML per-junction model replaces it
def clear_seconds(jam_m: float, reaction_s: float = 20, rate_mps: float = 2.0) -> float:
    return reaction_s + jam_m / rate_mps


# ponytail: fixed 50/50, tune from report cards
def blended_eta(routes_eta_s: float, distance_m: float, observed_speed_mps: float) -> float:
    return 0.5 * routes_eta_s + 0.5 * (distance_m / max(observed_speed_mps, 3))  # floor 3 m/s


def stage(eta_s: float, clear_s: float, buffer_s: float = 15):
    """None | "PREPARE" | "STOP". Caller fires each once per junction per run and handles inside-jam."""
    if eta_s <= 30:
        return "STOP"
    if eta_s <= clear_s + buffer_s:
        return "PREPARE"
    return None


if __name__ == "__main__":

    def jam(m):
        return [
            {"from_m": 0, "to_m": 600 - m, "speed": "NORMAL"},
            {"from_m": 600 - m, "to_m": 600, "speed": "TRAFFIC_JAM"},
        ]

    assert jam_metres(jam(500)) == 500 and jam_metres([]) == 0
    assert (
        jam_metres(
            [
                {"from_m": 0, "to_m": 100, "speed": "TRAFFIC_JAM"},
                {"from_m": 100, "to_m": 200, "speed": "NORMAL"},
                {"from_m": 200, "to_m": 300, "speed": "SLOW"},
                {"from_m": 300, "to_m": 400, "speed": "TRAFFIC_JAM"},
            ]
        )
        == 150
    )
    route = [
        {"from_m": 0, "to_m": 1000, "speed": "NORMAL"},
        {"from_m": 1000, "to_m": 1400, "speed": "TRAFFIC_JAM"},
        {"from_m": 1400, "to_m": 2000, "speed": "NORMAL"},
    ]
    assert (
        jam_metres(slice_intervals(route, 1100, 1700)) == 0
    )  # normal flow at the stop line: the jam is upstream
    assert jam_metres(slice_intervals(route, 800, 1300)) == 300  # window ends inside the jam
    assert slice_intervals(route, 1500, 1900) == [{"from_m": 1500, "to_m": 1900, "speed": "NORMAL"}]
    assert clear_seconds(500) > clear_seconds(100) and clear_seconds(0) == 20
    assert blended_eta(100, 300, 0) == 0.5 * 100 + 0.5 * 100  # speed floor 3
    assert stage(300, clear_seconds(500)) is None and stage(270, clear_seconds(500)) == "PREPARE"
    assert stage(100, clear_seconds(100)) is None and stage(30, clear_seconds(100)) == "STOP"
    print("leadtime ok")
