import pytest

from leadtime import blended_eta, clear_seconds, jam_metres, stage


def iv(a: float, b: float, speed: str) -> dict:
    return {"from_m": a, "to_m": b, "speed": speed}


def test_jam_metres_empty_and_normal() -> None:
    assert jam_metres([]) == 0
    assert jam_metres([iv(0, 500, "NORMAL")]) == 0


def test_jam_metres_walks_back_from_the_stop_line() -> None:
    spans = [
        iv(0, 100, "TRAFFIC_JAM"),
        iv(100, 200, "NORMAL"),
        iv(200, 300, "SLOW"),
        iv(300, 400, "TRAFFIC_JAM"),
    ]
    assert jam_metres(spans) == 150  # 100 jam + 50 slow, stops at the NORMAL span


def test_jam_metres_ignores_input_order() -> None:
    spans = [
        iv(300, 400, "TRAFFIC_JAM"),
        iv(0, 100, "TRAFFIC_JAM"),
        iv(200, 300, "SLOW"),
        iv(100, 200, "NORMAL"),
    ]
    assert jam_metres(spans) == 150


def test_jam_metres_full_queue() -> None:
    assert jam_metres([iv(0, 600, "TRAFFIC_JAM")]) == 600
    assert jam_metres([iv(0, 400, "SLOW")]) == 200


def test_clear_seconds() -> None:
    assert clear_seconds(0) == 20  # reaction time only
    assert clear_seconds(500) == 20 + 250
    assert clear_seconds(500, reaction_s=10, rate_mps=5) == 110


def test_blended_eta_is_an_even_mix() -> None:
    assert blended_eta(100, 600, 6) == 100  # 0.5 * 100 + 0.5 * (600 / 6)


def test_blended_eta_speed_floor() -> None:
    assert blended_eta(100, 300, 0) == 0.5 * 100 + 0.5 * 100  # 3 m/s floor
    assert blended_eta(100, 300, 2) == blended_eta(100, 300, 3)
    assert blended_eta(100, 300, 5) < blended_eta(100, 300, 3)


@pytest.mark.parametrize(
    ("eta", "clear", "want"),
    [
        (300, 270, None),  # 300 > 270 + 15
        (285, 270, "PREPARE"),  # exactly clear + buffer
        (286, 270, None),
        (31, 10, None),
        (30.1, 270, "PREPARE"),
        (30, 270, "STOP"),  # STOP threshold is inclusive
        (30, 0, "STOP"),
        (0, 270, "STOP"),
    ],
)
def test_stage_thresholds(eta: float, clear: float, want: str | None) -> None:
    assert stage(eta, clear) == want


def test_stage_buffer_is_configurable() -> None:
    assert stage(100, 80, buffer_s=30) == "PREPARE"
    assert stage(100, 80, buffer_s=15) is None
