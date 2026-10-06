"""/location: side effects after the response, one Routes call per run, the monotonic junction index. Ticks are sent by
calling the endpoint directly with a BackgroundTasks of our own, so what happens before and after the response is visible
(TestClient runs background tasks before it returns)."""

import asyncio
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

import main
import routes_api
from corridor import CORRIDORS, SCENARIOS, distance_m
from fakefs import FakeFirestore
from test_api import BLR_HOSPITAL, run_doc, start

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
BLR = CORRIDORS["blr"]
J = [(j["lat"], j["lng"]) for j in BLR["junctions"]]
HOSP = (BLR["hospital"]["lat"], BLR["hospital"]["lng"])
START = (J[0][0], J[0][1] + 400 / (111320 * math.cos(math.radians(J[0][0]))))  # 400 m east of j1
PTS = [START, *J, HOSP]  # the route: start, j1 .. j5, hospital
CUM = [0.0]
for _a, _b in zip(PTS, PTS[1:], strict=False):
    CUM.append(CUM[-1] + distance_m(_a, _b))
PACE = 10.0  # m/s the stubbed route is driven at


def at(m: float, north: float = 0.0) -> tuple[float, float]:
    """The point m metres along the route, `north` metres off it."""
    i = max(k for k in range(len(PTS) - 1) if CUM[k] <= m)
    f = (m - CUM[i]) / (CUM[i + 1] - CUM[i])
    return PTS[i][0] + f * (PTS[i + 1][0] - PTS[i][0]) + north / 111320, PTS[i][1] + f * (
        PTS[i + 1][1] - PTS[i][1]
    )


def route_result(jam: tuple[float, float] | None = None) -> dict:
    """What routes_api.traffic_to_point returns for START -> hospital, with one TRAFFIC_JAM span (route metres) if given."""
    spans = (
        [(0.0, CUM[-1], "NORMAL")]
        if jam is None
        else [
            (0.0, jam[0], "NORMAL"),
            (jam[0], jam[1], "TRAFFIC_JAM"),
            (jam[1], CUM[-1], "NORMAL"),
        ]
    )
    return {
        "polyline_points": PTS,
        "duration_s": CUM[-1] / PACE,
        "intervals": [{"from_m": a, "to_m": b, "speed": s} for a, b, s in spans],
        "steps": [],
        "age_s": 0,
        "stale": False,
    }


class Route:
    """The stubbed Routes call: `result` is what it returns, `calls` what it was asked."""

    def __init__(self) -> None:
        self.result: dict = route_result()
        self.calls: list[dict] = []

    def __call__(
        self, origin: Any, dest: Any, key: Any = None, ttl: float = 20, steps: bool = False, **ctx: Any
    ) -> dict:
        self.calls.append({"origin": origin, "key": key, "ttl": ttl, **ctx})
        return self.result


@pytest.fixture
def route(monkeypatch: pytest.MonkeyPatch) -> Route:
    stub = Route()
    monkeypatch.setattr(main.routes_api, "traffic_to_point", stub)
    return stub


def live_run(client: TestClient, *, tier: str | None = "critical") -> str:
    rid = start(client, source="sim", destination=BLR_HOSPITAL)
    if tier:
        client.post(f"/runs/{rid}/confirm", json={"tier": tier})
    return rid


def send(rid: str, seq: int, pos: tuple[float, float], speed: float = PACE) -> tuple[Any, BackgroundTasks]:
    """One tick, 5 s after the last; returns the response and the background tasks it queued, not yet run."""
    bg = BackgroundTasks()
    t = T0 + timedelta(seconds=5 * seq)
    loc = main.Loc(run_id=rid, lat=pos[0], lng=pos[1], speed_mps=speed, t=t, source="sim")
    return main.location(loc, bg, idempotency_key=None), bg


def finish(bg: BackgroundTasks) -> None:
    asyncio.run(bg())


# ---- 1. side effects after the response ------------------------------------------------------------------------------


def test_alert_voice_rationale_and_brief_run_after_the_response(
    client: TestClient, seeded: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    spoken: list[tuple] = []
    rationales: list[tuple] = []

    def speak(text: str, lang: str, path: str) -> tuple[str, str]:
        spoken.append((text, lang, path))
        return "https://x/a.mp3", "ಸ್ಥಳೀಯ"

    monkeypatch.setattr(main, "speak", speak)

    def rationale(jid: str, seq: list, lang: str) -> None:
        rationales.append((jid, len(seq), lang))

    monkeypatch.setattr(main, "rationale", rationale)
    rid = start(client, scenario="blr-two-vehicles", source="sim", destination=BLR_HOSPITAL)
    client.post(f"/runs/{rid}/confirm", json={"tier": "critical"})
    alerts = seeded.collection("runs").document(rid).collection("alerts")
    for seq, k in enumerate(SCENARIOS["blr-two-vehicles"]["vehicles"][0]["ticks"]):
        out, bg = send(rid, seq, (k["lat"], k["lng"]), k["speed_mps"])
        if out["alerts_fired"]:
            break
    else:
        raise AssertionError("the scenario fired no alert")

    # the response is out and Firestore is written, nothing slow has run yet
    assert spoken == [] and rationales == []
    stored = [d.to_dict() for d in alerts.stream()]
    assert stored and all(a["audio_url"] is None and a["text_local"] is None for a in stored)
    assert run_doc(seeded, rid)["alert_count"] == len(stored)
    assert seeded.collection("audit").stream()  # preemption is requested in the request
    finish(bg)

    assert [s[1] for s in spoken] == ["kn"] and spoken[0][2].startswith(f"alerts/{rid}/")
    patched = [d.to_dict() for d in alerts.stream()]
    assert patched[0]["audio_url"] == "https://x/a.mp3" and patched[0]["text_local"] == "ಸ್ಥಳೀಯ"
    assert patched[0]["text"] == spoken[0][0] and patched[0]["text"] == stored[0]["text"]
    assert len(rationales) == 1 and rationales[0][0].startswith("blr_")


def test_a_failed_synthesis_leaves_the_alert_as_text_only(
    client: TestClient, seeded: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "speak", lambda text, lang, path: (None, None))
    rid = start(client, scenario="blr-two-vehicles", source="sim", destination=BLR_HOSPITAL)
    client.post(f"/runs/{rid}/confirm", json={"tier": "critical"})
    for seq, k in enumerate(SCENARIOS["blr-two-vehicles"]["vehicles"][0]["ticks"]):
        out, bg = send(rid, seq, (k["lat"], k["lng"]), k["speed_mps"])
        finish(bg)
        if out["alerts_fired"]:
            break
    a = seeded.collection("runs").document(rid).collection("alerts").document("0").get().to_dict()
    assert a["audio_url"] is None and a["text_local"] is None and a["text"]


def test_a_background_error_is_logged_not_raised(
    client: TestClient,
    seeded: FakeFirestore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def boom(*_: Any) -> None:
        raise RuntimeError("tts exploded")

    monkeypatch.setattr(main, "speak", boom)
    rid = start(client, scenario="blr-two-vehicles", source="sim", destination=BLR_HOSPITAL)
    for seq, k in enumerate(SCENARIOS["blr-two-vehicles"]["vehicles"][0]["ticks"]):
        out, bg = send(rid, seq, (k["lat"], k["lng"]), k["speed_mps"])
        finish(bg)  # must not raise
        if out["alerts_fired"]:
            break
    assert '"event": "background_error"' in capsys.readouterr().out


def test_the_brief_is_written_after_the_tick_is_answered(client: TestClient, seeded: FakeFirestore) -> None:
    far = {"name": "H", "lat": 12.9145 + 0.018, "lng": 77.6361}  # about 2 km north
    rid = start(client, scenario="blr-two-vehicles", source="sim", destination=far)
    seeded.collection("runs").document(rid).collection("log").document("1").set(
        {"t": datetime.now(UTC), "fields": {}}
    )
    for seq, dlat in enumerate((0, 0.0006)):
        finish(send(rid, seq, (12.9145 + dlat, 77.6361))[1])
    out, bg = send(rid, 2, (12.9145 + 0.006, 77.6361))  # 660 m driven, ETA under 300 s
    assert out["brief_due"] is True
    assert (
        run_doc(seeded, rid)["brief_due"] is True
        and not seeded.collection("briefs").document(rid).get().exists
    )
    finish(bg)
    run = run_doc(seeded, rid)
    assert (run["brief_fired"], run["brief_due"]) == (True, False)
    assert seeded.collection("briefs").document(rid).get().exists


def test_a_failed_brief_stays_due_for_the_regenerate_button(
    client: TestClient, seeded: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: Any, **__: Any) -> None:
        raise main.ExtractionFailed("no")

    monkeypatch.setattr(main.brief, "generate", fail)
    far = {"name": "H", "lat": 12.9145 + 0.018, "lng": 77.6361}
    rid = start(client, scenario="blr-two-vehicles", source="sim", destination=far)
    seeded.collection("runs").document(rid).collection("log").document("1").set({"t": datetime.now(UTC)})
    for seq, dlat in enumerate((0, 0.0006, 0.006)):
        finish(send(rid, seq, (12.9145 + dlat, 77.6361))[1])
    run = run_doc(seeded, rid)
    assert (run["brief_due"], run["brief_fired"]) == (True, False)


# ---- 2. one Routes call per run --------------------------------------------------------------------------------------


def test_one_route_call_serves_every_junction_ahead(
    client: TestClient, seeded: FakeFirestore, route: Route
) -> None:
    route.result = route_result(jam=(CUM[2] - 300, CUM[2]))  # a 300 m queue at j2's stop line
    rid = live_run(client)
    out, bg = send(rid, 0, START)
    finish(bg)
    calls = route.calls
    assert len(calls) == 1 and calls[0]["key"] == (rid, "route") and calls[0]["junction_id"] is None
    assert out["traffic"] == "live" and out["next_junction"] == "blr_j1" and out["jam_m"] == 0
    run = run_doc(seeded, rid)
    assert run["ahead_ids"] == [f"blr_j{i}" for i in range(1, 6)]
    # ETA from the route's own pace: distance to the junction at 10 m/s, and the observed speed is 10 m/s too
    assert [run["ahead"][f"blr_j{i}"]["eta_s"] for i in (1, 5)] == pytest.approx(
        [CUM[1] / PACE, CUM[5] / PACE], abs=3
    )
    alerts = [d.to_dict() for d in seeded.collection("runs").document(rid).collection("alerts").stream()]
    assert [(a["junction_id"], a["stage"]) for a in alerts] == [("blr_j2", "PREPARE")]  # only j2 has a queue
    assert alerts[0]["jam_m"] == pytest.approx(300, abs=25)
    out2, bg2 = send(rid, 1, at(50))
    finish(bg2)
    assert len(route.calls) == 2  # one more call for the next tick, still not one per junction


def test_the_real_call_is_throttled_to_one_per_20_seconds(
    client: TestClient, seeded: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    posts: list[str] = []
    clock = [100.0]
    monkeypatch.setattr(routes_api, "_cache", {})
    monkeypatch.setattr(
        routes_api, "_read_shared", lambda key, ctx: None
    )  # this is the memory layer's throttle
    monkeypatch.setattr(routes_api.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(routes_api, "parse", lambda r: route_result())

    class Reply:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict:
            return {"routes": [{}]}

    def post(url: str, **kw: Any) -> Reply:
        posts.append(url)
        return Reply()

    monkeypatch.setattr(routes_api.httpx, "post", post)
    rid = live_run(client)
    for seq in range(4):  # 15 s of ticks, five junctions ahead throughout
        finish(send(rid, seq, at(seq * 50))[1])
        clock[0] += 5
    assert len(posts) == 1
    clock[0] += 10  # 25 s since the first call
    finish(send(rid, 4, at(200))[1])
    assert len(posts) == 2


def test_without_a_route_the_queue_reads_as_normal_and_traffic_is_stale(
    client: TestClient, seeded: FakeFirestore, route: Route
) -> None:
    route.result = {"polyline_points": [], "duration_s": None, "intervals": [], "steps": [], "stale": True}
    rid = live_run(client)
    out, bg = send(rid, 0, START)
    finish(bg)
    assert out["state"] == "en_route" and out["traffic"] == "stale" and out["jam_m"] in (0, None)


# ---- 3. monotonic junction index -------------------------------------------------------------------------------------


def test_route_index_never_goes_back_and_a_jump_over_a_junction_is_a_pass(
    client: TestClient, seeded: FakeFirestore, route: Route
) -> None:
    rid = live_run(client)
    j1 = CUM[1]
    steps = [
        (
            at(j1 - 100, north=70),
            0,
            "blr_j1",
        ),  # 100 m before j1, 70 m to the side: never inside its 60 m circle
        (at(j1 - 60, north=70), 0, "blr_j1"),
        (
            at(j1 + 60, north=70),
            1,
            "blr_j2",
        ),  # 120 m in one 5 s tick across j1: passed by position along the route
        (at(j1 - 20), 1, "blr_j2"),  # a GPS jump back before j1 does not bring j1 back
        (at(j1 + 100), 1, "blr_j2"),
    ]
    for seq, (pos, index, nxt) in enumerate(steps):
        out, bg = send(rid, seq, pos)
        finish(bg)
        run = run_doc(seeded, rid)
        assert (run["route_index"], out["next_junction"]) == (index, nxt), seq
        assert run["passed_junctions"] == [f"blr_j{i}" for i in range(1, index + 1)]


def test_passing_a_later_junction_passes_the_earlier_ones(
    client: TestClient, seeded: FakeFirestore, route: Route
) -> None:
    rid = live_run(client)
    finish(send(rid, 0, at(10))[1])
    out, bg = send(rid, 1, at(CUM[3] + 60))  # a long gap in ticks: j1, j2 and j3 are all behind
    finish(bg)
    assert run_doc(seeded, rid)["route_index"] == 3 and out["next_junction"] == "blr_j4"


def test_a_run_without_route_index_resumes_from_its_passed_junctions(
    client: TestClient, seeded: FakeFirestore, route: Route
) -> None:
    rid = live_run(client)
    seeded.collection("runs").document(rid).update({"passed_junctions": ["blr_j1", "blr_j2"]})
    out, bg = send(rid, 0, at(10))  # on the route, j1 and j2 still ahead of this position
    finish(bg)
    assert out["next_junction"] == "blr_j3" and run_doc(seeded, rid)["route_index"] == 2


def test_a_circle_crossing_in_one_jump_passes_the_junction_without_a_route(
    client: TestClient, seeded: FakeFirestore
) -> None:
    """Replay mode has no route polyline: the step from the last tick through the stop-line circle still counts."""
    rid = start(client, scenario="blr-two-vehicles", source="sim", destination=BLR_HOSPITAL)
    before, after = (
        (J[0][0], J[0][1] + 90 / 108500),
        (J[0][0], J[0][1] - 90 / 108500),
    )  # 90 m either side of j1
    finish(send(rid, 0, before)[1])
    out, bg = send(rid, 1, after)  # 180 m in one tick, straight through the circle
    finish(bg)
    assert run_doc(seeded, rid)["route_index"] == 1 and out["next_junction"] != "blr_j1"
