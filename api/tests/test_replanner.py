"""The constable re-planner: tools, guard, apply, fallbacks, and the cop-note trigger. The ADK runner is a scripted fake (as in
test_agent.py); the model, Vertex and Routes are never called."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from typing import Any

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

import copnote
import main
import replanner
from corridor import CORRIDORS
from fakefs import FakeFirestore
from test_agent import call, event, respond
from test_api import BLR_HOSPITAL, alerting_run, start
from test_api import tick as send_tick
from test_location import Route, route_result

ALT = {"name": "Via Hosur Road", "eta_delta_s": 45, "points": [[12.91, 77.6], [12.92, 77.61]]}


class World:
    """A scenario ambulance with an alert and a green phase at `jid`, plus two more runs heading for it: another critical
    ambulance (b) and an urgent one (c)."""

    def __init__(self, client: TestClient, db: FakeFirestore) -> None:
        self.db = db
        self.a, n = alerting_run(client, db)
        self.jid: str = (
            db.collection("runs")
            .document(self.a)
            .collection("alerts")
            .document(str(n))
            .get()
            .to_dict()["junction_id"]
        )
        self.alert = db.collection("runs").document(self.a).collection("alerts").document(str(n))
        base = db.collection("runs").document(self.a).get().to_dict() or {}
        for rid, tier, eta, ap in (("run-b", "critical", 40, "SE"), ("run-c", "urgent", 70, "NE")):
            db.collection("runs").document(rid).set(
                {
                    **base,
                    "confirmed_tier": tier,
                    "ahead_ids": [self.jid],
                    "ahead": {self.jid: {"eta_s": eta, "approach": ap}},
                }
            )
        db.collection("runs").document(self.a).update({"ahead": {self.jid: {"eta_s": 30, "approach": "E"}}})
        self.note = {
            "kind": "cannot_clear",
            "extra_seconds": None,
            "reason": "crowd",
            "transcript_en": "crowd on the road",
        }
        copnote.apply(db, self.jid, self.note, datetime.now(UTC))  # the note doc the plan is stored on

    def run(self, *ids: str) -> dict:
        replanner.run(self.jid, 0, self.note, list(ids) or [self.a])
        return self.replan

    @property
    def replan(self) -> dict:
        return (self.db.collection("junctions").document(self.jid).get().to_dict() or {})["replan"]

    @property
    def junction(self) -> dict:
        return self.db.collection("junctions").document(self.jid).get().to_dict() or {}

    def audit(self, action: str) -> list[dict]:
        return [d.to_dict() for d in self.db.collection("audit").stream() if d.to_dict()["action"] == action]

    def run_doc(self, rid: str) -> dict:
        return self.db.collection("runs").document(rid).get().to_dict() or {}


@pytest.fixture
def world(client: TestClient, seeded: FakeFirestore, monkeypatch: pytest.MonkeyPatch) -> World:
    monkeypatch.setitem(CORRIDORS["blr"], "alt_route", ALT)
    return World(client, seeded)


class FakeSessions:
    state: dict = {}

    async def create_session(self, **kw: Any) -> None:
        FakeSessions.state = kw["state"]


def install(monkeypatch: pytest.MonkeyPatch, events: list[NS], delay: float = 0) -> None:
    class FakeRunner:
        def __init__(self, **_: object) -> None: ...

        async def run_async(self, **_: object) -> AsyncIterator[NS]:
            for ev in events:
                await asyncio.sleep(delay)
                yield ev

    monkeypatch.setattr(replanner, "offline", lambda: False)
    monkeypatch.setattr(replanner, "HAVE_ADK", True)
    monkeypatch.setattr(replanner, "InMemorySessionService", FakeSessions, raising=False)
    monkeypatch.setattr(replanner, "Runner", FakeRunner, raising=False)
    monkeypatch.setattr(replanner, "corridor_replanner", None, raising=False)


def plan(action: str, run_id: str | None = None, reason: str = "because", **details: Any) -> dict[str, Any]:
    return {"action": action, "run_id": run_id, "details": details, "reason": reason, "confidence": 0.8}


def script(final: Any, jid: str, notify: bool = False) -> list[NS]:
    """What the model does: look at the junction, ask for options, maybe tell control, then answer."""
    st, opts = call("junction_state", junction_id=jid), call("resequence_options", junction_id=jid)
    state = {"phase": {"approach": "E", "seconds_left": 40}, "contenders": [1, 2], "queue_m": {"E": 120}}
    evs = [
        event(st),
        event(respond(st, state)),
        event(opts),
        event(respond(opts, {"swaps": [["a", "b"]], "holdable": ["run-c"]})),
    ]
    if notify:
        n = call("notify_control", text="rerouting the ambulance")
        evs += [event(n), event(respond(n, {"ok": True}))]
    text = final if isinstance(final, str) else json.dumps(final)
    return [*evs, event(NS(function_call=None, function_response=None, text=text), final=True)]


# ---- valid plans are applied --------------------------------------------------------------------------------------------


def test_a_valid_reroute_is_applied_and_recorded(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    alt = call("alternative_route", run_id=world.a)
    evs = script(plan("reroute", world.a, reason="the east approach is blocked"), world.jid)
    evs[-1:-1] = [event(alt), event(respond(alt, {"available": True, "eta_delta_s": 45}))]
    install(monkeypatch, evs)
    rec = world.run()
    assert rec["plan"]["action"] == "reroute" and rec["guard"] is None
    assert rec["action_text"] == "Rerouted via the alternative route (+45 s)"
    ov = world.run_doc(world.a)["route_override"]
    assert (
        ov["source"] == "scenario_file"
        and ov["eta_delta_s"] == 45
        and ov["points"] == [12.91, 77.6, 12.92, 77.61]
    )
    assert FakeSessions.state == {"junction_id": world.jid}
    lines = [t["text"] for t in rec["trace"]]
    assert (
        lines[0]
        == f"called junction_state({world.jid}) → 2 vehicles, queue {{'E': 120}} m, green E 40 s left"
    )
    assert lines[-1] == f"called alternative_route({world.a}) → +45 s vs current"
    assert all(t.get("text") for t in rec["trace"])
    (audit,) = world.audit("replan")
    assert (audit["plan_action"], audit["run_id"], audit["guard"]) == ("reroute", world.a, None)
    note = (
        world.db.collection("duty").document(world.jid).collection("notes").document("0").get().to_dict()
        or {}
    )
    assert note["replan"]["plan"]["action"] == "reroute" and note["replan"]["decided_at"] <= datetime.now(UTC)


def test_a_valid_equal_tier_swap_is_written_through_the_signal_adapter(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = world.junction["phase"]
    assert [c["run_id"] for c in replanner.junction_state(world.jid)["contenders"]] == [
        world.a,
        "run-b",
        "run-c",
    ]
    install(monkeypatch, script(plan("resequence", order=["run-b", world.a, "run-c"]), world.jid))
    rec = world.run()
    assert rec["guard"] is None and rec["action_text"] == "Order changed within the same tier"
    ph = world.junction["phase"]
    assert [s["run_id"] for s in ph["sequence"]] == ["run-b", world.a, "run-c"] and ph["run_ids"] == [
        "run-b",
        world.a,
        "run-c",
    ]
    assert [s["offset_s"] for s in ph["sequence"]] == [
        0,
        12,
        24,
    ]  # offsets stay with the positions, tiers with theirs
    assert ph["approach"] == "SE" and ph["until"] >= before["until"] - timedelta(seconds=5)
    assert world.junction["last_sequence"]["sequence"] == ph["sequence"]
    assert (
        ph["rationale"] == "Order changed by the re-planner, within the same tier."
        and "rationale_local" not in ph
    )
    assert world.junction["last_sequence"]["rationale"] == ph["rationale"]


def test_a_valid_hold_delays_the_lower_tier_vehicle_and_those_after_it(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.db.collection("runs").document("run-d").set(
        {
            **world.run_doc("run-c"),
            "confirmed_tier": "stable",
            "ahead": {world.jid: {"eta_s": 90, "approach": "S"}},
        }
    )
    install(monkeypatch, script(plan("hold", "run-c", hold_s=40), world.jid))
    rec = world.run()
    assert rec["guard"] is None and rec["action_text"] == "Lower-tier vehicle held 40 s"
    seq = world.junction["phase"]["sequence"]
    assert [(s["run_id"], s["offset_s"]) for s in seq] == [
        (world.a, 0),
        ("run-b", 12),
        ("run-c", 64),
        ("run-d", 76),
    ]
    assert "held 40 s" in world.junction["phase"]["rationale"]


def replans(world: World) -> list[dict]:
    """The escalation audit entries the re-planner wrote (the cop note's own one is from the setup)."""
    return [e for e in world.audit("escalation") if e["reason"] == "replan_escalate"]


def test_escalate_flags_the_unacked_alert_once_and_notifies_control(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.alert.update({"escalated": False, "acked_at": None})
    install(
        monkeypatch, script(plan("escalate", reason="two runs, one blocked approach"), world.jid, notify=True)
    )
    rec = world.run()
    assert rec["action_text"] == "Escalated to control" and rec["guard"] is None
    a = world.alert.get().to_dict() or {}
    assert a["escalated"] is True and a["escalation_reason"] == "replan_escalate"
    (esc,) = replans(world)
    assert (esc["run_id"], esc["reason"], esc["junction_id"]) == (world.a, "replan_escalate", world.jid)
    assert (
        len(world.audit("notify_control")) == 0
    )  # the model's own notify_control call is a tool the fake does not run
    world.run()  # nothing left to flag
    assert len(replans(world)) == 1 and len(world.audit("replan")) == 2


def test_escalate_without_the_model_notifying_notifies_control_itself(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, script(plan("escalate", reason="unsure"), world.jid))
    world.run()
    (n,) = world.audit("notify_control")
    assert n["text"] == "unsure" and n["junction_id"] == world.jid


def test_confidence_is_clamped_and_alerts_elsewhere_are_left_alone(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert replanner.parse(json.dumps({**plan("no_change"), "confidence": 7}))["confidence"] == 1.0
    assert replanner.parse(json.dumps({**plan("no_change"), "confidence": "high"}))["confidence"] is None
    world.alert.update(
        {"escalated": False, "acked_at": None, "junction_id": "blr_j1"}
    )  # another junction's alert
    install(monkeypatch, script(plan("escalate"), world.jid))
    world.run()
    assert (world.alert.get().to_dict() or {})["escalated"] is False and replans(world) == []


def test_no_change_changes_nothing(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    before = world.junction["phase"]
    install(monkeypatch, script(plan("no_change", reason="the rules cover it"), world.jid))
    rec = world.run()
    assert rec["action_text"] == "No change" and world.junction["phase"] == before
    assert "route_override" not in world.run_doc(world.a) and world.audit("notify_control") == []


# ---- the guard: anything unsafe becomes escalate + notify_control -------------------------------------------------------------


def guarded(world: World, monkeypatch: pytest.MonkeyPatch, final: Any, guard: str) -> dict:
    before, notified = world.junction["phase"], len(world.audit("notify_control"))
    install(monkeypatch, script(final, world.jid))
    rec = world.run()
    assert (
        rec["guard"] == guard
        and rec["plan"]["action"] == "escalate"
        and rec["action_text"] == "Escalated to control"
    )
    assert rec["trace"][-1]["guard"] == guard and rec["trace"][-1]["text"].startswith(f"guard: {guard}")
    assert rec["plan"]["reason"] == f"Safety check: {guard}."
    assert world.junction["phase"] == before and "route_override" not in world.run_doc(world.a)
    assert len(world.audit("notify_control")) == notified + 1 and world.audit("replan")[-1]["guard"] == guard
    return rec


def test_a_reroute_that_arrives_too_late_is_rejected(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(CORRIDORS["blr"], "alt_route", {**ALT, "eta_delta_s": 121})
    guarded(world, monkeypatch, plan("reroute", world.a), "eta_too_long")


def test_a_reroute_exactly_at_the_slack_is_allowed(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(CORRIDORS["blr"], "alt_route", {**ALT, "eta_delta_s": 120})
    install(monkeypatch, script(plan("reroute", world.a), world.jid))
    assert world.run()["guard"] is None


def test_a_reroute_to_another_destination_or_without_an_alternative_is_rejected(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    guarded(
        world, monkeypatch, plan("reroute", world.a, destination="Fortis Hospital"), "destination_changed"
    )
    monkeypatch.delitem(CORRIDORS["blr"], "alt_route")
    guarded(world, monkeypatch, plan("reroute", world.a), "no_alternative")


def test_a_resequence_across_tiers_is_rejected(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    guarded(world, monkeypatch, plan("resequence", order=[world.a, "run-c", "run-b"]), "tier_change")
    guarded(world, monkeypatch, plan("resequence", order=["run-c", world.a, "run-b"]), "tier_change")


def test_a_hold_on_the_highest_tier_is_rejected(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    guarded(world, monkeypatch, plan("hold", world.a, hold_s=30), "hold_highest_tier")
    guarded(world, monkeypatch, plan("hold", "run-b", hold_s=30), "hold_highest_tier")  # tied for the top


def test_a_reply_that_touches_a_tier_is_rejected(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    guarded(world, monkeypatch, {**plan("no_change"), "tier": "critical"}, "tier_change")
    guarded(world, monkeypatch, plan("hold", "run-c", hold_s=30, tier="stable"), "tier_change")


@pytest.mark.parametrize(
    ("final", "guard"),
    [
        (plan("launch_missiles"), "unknown_action"),
        ("[1, 2]", "unknown_action"),
        (plan("hold", "run-c", hold_s=61), "hold_too_long"),
        (plan("hold", "run-c", hold_s=0), "hold_too_long"),
        (plan("hold", "run-c", hold_s="30"), "hold_too_long"),
        (plan("hold", "run-nowhere", hold_s=30), "unknown_run"),
        (plan("reroute", "run-nowhere"), "unknown_run"),
        (plan("resequence", order=["run-b"]), "unknown_run"),
        (plan("resequence", order="run-b"), "unknown_run"),
    ],
)
def test_other_unsafe_plans_are_rejected(
    world: World, monkeypatch: pytest.MonkeyPatch, final: Any, guard: str
) -> None:
    guarded(world, monkeypatch, final, guard)


def test_the_guard_judges_the_state_in_the_database_not_the_models_trace(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    ev = script(plan("reroute", world.a), world.jid)
    alt = call("alternative_route", run_id=world.a)
    ev[-1:-1] = [
        event(alt),
        event(respond(alt, {"available": True, "eta_delta_s": -300})),
    ]  # the tool "said" faster
    monkeypatch.setitem(CORRIDORS["blr"], "alt_route", {**ALT, "eta_delta_s": 500})
    install(monkeypatch, ev)
    assert world.run()["guard"] == "eta_too_long"


# ---- failures: always an answer -----------------------------------------------------------------------------------------


def test_a_timeout_falls_back_to_escalate(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, script(plan("no_change"), world.jid), delay=0.2)
    monkeypatch.setattr(replanner, "TIMEOUT_S", 0.05)
    rec = world.run()
    assert rec["plan"]["action"] == "escalate" and rec["guard"] is None
    assert rec["trace"] == [{"fallback": "TimeoutError", "text": "fallback (TimeoutError): escalate"}]
    assert (
        rec["plan"]["reason"] == "Re-planner unavailable (TimeoutError)."
        and len(world.audit("notify_control")) == 1
    )


def test_bad_json_falls_back(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, script("not json", world.jid))
    assert world.run()["trace"][0]["fallback"] == "JSONDecodeError"


def test_offline_is_a_fixed_escalate_plan(world: World) -> None:
    rec = world.run()  # OFFLINE_AI=1 in the test env
    assert rec["plan"] == {
        "action": "escalate",
        "run_id": None,
        "details": {},
        "reason": "Fixed escalation: no model available.",
        "confidence": None,
    }
    assert rec["trace"] == [{"fallback": "offline_ai", "text": "fallback (offline_ai): escalate"}]
    assert rec["action_text"] == "Escalated to control" and rec["guard"] is None
    assert len(world.audit("replan")) == 1


def test_without_adk_it_is_the_same_fixed_plan(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(replanner, "offline", lambda: False)
    monkeypatch.setattr(replanner, "HAVE_ADK", False)
    assert world.run()["trace"][0]["fallback"] == "adk_missing"


def test_run_never_raises(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any) -> None:
        raise RuntimeError("firestore down")

    monkeypatch.setattr(replanner, "decide", boom)
    replanner.run(world.jid, 0, world.note, [world.a])  # logged, not raised
    assert world.audit("replan") == []


def test_a_note_for_a_junction_doc_that_does_not_exist_yet_is_stored(world: World) -> None:
    world.db.collection("junctions").document(world.jid).delete()
    replanner.run(world.jid, 7, world.note, [world.a])
    assert world.junction["replan"]["note_n"] == 7


# ---- the trigger in copnote ---------------------------------------------------------------------------------------------


def apply_note(world: World, bg: BackgroundTasks, **raw: Any) -> dict:
    return copnote.apply(
        world.db, world.jid, {"reason": "r", "transcript_en": "t", **raw}, datetime.now(UTC), bg
    )


@pytest.mark.parametrize(
    ("raw", "scheduled"),
    [
        ({"kind": "cannot_clear"}, True),
        ({"kind": "delay", "extra_seconds": 91}, True),
        ({"kind": "delay", "extra_seconds": 90}, False),
        ({"kind": "delay", "extra_seconds": None}, False),  # the 60 s default
        ({"kind": "cleared"}, False),
        ({"kind": "other"}, False),
    ],
)
def test_copnote_schedules_the_replanner_only_for_cannot_clear_or_a_long_delay(
    world: World, raw: dict, scheduled: bool
) -> None:
    bg = BackgroundTasks()
    apply_note(world, bg, **raw)
    assert [(t.func, t.args[:1]) for t in bg.tasks] == ([(replanner.run, (world.jid,))] if scheduled else [])
    if scheduled:
        assert world.audit("replan") == []  # not before the response: it runs as a background task
        args: Any = bg.tasks[0].args
        _, n, note, run_ids = args
        assert (n, note["kind"], run_ids) == (1, raw["kind"], [world.a])  # the runs that had an alert here


def test_copnote_does_not_schedule_without_runs_ahead_or_when_disabled(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    bg = BackgroundTasks()
    monkeypatch.setenv("REPLANNER_DISABLED", "1")
    apply_note(world, bg, kind="cannot_clear")
    assert bg.tasks == [] and replanner.disabled()
    monkeypatch.delenv("REPLANNER_DISABLED")
    world.db.collection("runs").document(world.a).update({"ahead_ids": []})
    apply_note(world, bg, kind="cannot_clear")
    assert bg.tasks == []
    world.db.collection("runs").document(world.a).update({"ahead_ids": [world.jid]})
    apply_note(world, bg, kind="cannot_clear")
    assert len(bg.tasks) == 1
    bg.tasks.clear()
    copnote.apply(
        world.db, world.jid, {"kind": "cannot_clear"}, datetime.now(UTC)
    )  # no bg: the old signature still works
    assert bg.tasks == []


def test_the_endpoint_runs_the_replanner_after_the_response(
    client: TestClient, seeded: FakeFirestore
) -> None:
    rid, n = alerting_run(client, seeded)
    jid = (
        seeded.collection("runs")
        .document(rid)
        .collection("alerts")
        .document(str(n))
        .get()
        .to_dict()["junction_id"]
    )
    client.post("/duty", json={"corridor": "blr", "junction_id": jid, "device_id": "cop-1", "on": True})
    r = client.post("/cop-note", json={"corridor": "blr", "junction_id": jid, "text": "a bus has stalled"})
    assert r.status_code == 200 and "replan" not in r.json()  # the answer is the rules' alone
    rec = (seeded.collection("junctions").document(jid).get().to_dict() or {})["replan"]
    assert (
        rec["plan"]["action"] == "escalate" and rec["trace"][0]["fallback"] == "offline_ai"
    )  # OFFLINE_AI stub
    stored = seeded.collection("duty").document(jid).collection("notes").document("0").get().to_dict() or {}
    assert stored["replan"]["action_text"] == "Escalated to control"


# ---- tools --------------------------------------------------------------------------------------------------------------


def test_junction_state_reports_phase_queue_and_contenders(world: World) -> None:
    world.db.collection("junctions").document(world.jid).update(
        {"cop_block_until": datetime.now(UTC) + timedelta(seconds=200)}
    )
    s = replanner.junction_state(world.jid)
    assert s["junction_id"] == world.jid and s["cop_blocked"] is True
    assert s["phase"] and s["phase"]["approach"] and s["phase"]["seconds_left"] > 0
    assert [(c["run_id"], c["tier"], c["rank"], c["eta_s"]) for c in s["contenders"]] == [
        (world.a, "critical", 1, 30),
        ("run-b", "critical", 1, 40),
        ("run-c", "urgent", 3, 70),
    ]
    assert list(s["queue_m"]) == [world.alert.get().to_dict()["approach"]]  # the alert's jam_m, per approach
    json.dumps(s, default=str)
    world.db.collection("junctions").document(world.jid).update({"phase": None})
    assert replanner.junction_state(world.jid)["phase"] is None


def test_resequence_options_are_the_equal_tier_swaps_and_the_holdable(world: World) -> None:
    o = replanner.resequence_options(world.jid)
    assert o["current_order"] == [world.a, "run-b", "run-c"] and o["max_hold_s"] == 60
    assert o["swaps"] == [["run-b", world.a, "run-c"]] and o["holdable"] == ["run-c"]
    for order in o["swaps"]:  # whatever it offers passes the guard
        replanner.validate(plan("resequence", order=order), {**replanner.junction_state(world.jid)})
    world.db.collection("runs").document("run-b").update({"ahead_ids": []})
    assert replanner.resequence_options(world.jid)["swaps"] == []  # tiers differ: nothing to swap


def test_orders_cap_and_keep_rank_positions() -> None:
    seq = [{"run_id": f"r{i}", "rank": 1} for i in range(4)]
    orders = replanner._orders(seq)
    assert len(orders) == replanner.MAX_OPTIONS and all(sorted(o) == ["r0", "r1", "r2", "r3"] for o in orders)
    mixed = [{"run_id": "a", "rank": 1}, {"run_id": "b", "rank": 3}, {"run_id": "c", "rank": 1}]
    assert replanner._orders(mixed) == [["c", "b", "a"]]
    assert replanner._holdable(mixed) == ["b"] and replanner._holdable([]) == []


def test_alternative_route_in_scenario_mode_reads_the_corridor_file(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.db.collection("runs").document(world.a).update({"eta_hospital_s": 600})
    out = replanner.alternative_route(world.a)
    assert out == {
        "source": "scenario_file",
        "name": "Via Hosur Road",
        "run_id": world.a,
        "available": True,
        "eta_delta_s": 45,
        "current_eta_s": 600,
        "alt_eta_s": 645,
        "destination": world.run_doc(world.a)["destination"]["name"],
    }
    monkeypatch.delitem(CORRIDORS["blr"], "alt_route")
    assert replanner.alternative_route(world.a) == {"run_id": world.a, "available": False, "source": "none"}
    assert replanner.alternative_route("run-nowhere")["available"] is False
    world.db.collection("runs").document(world.a).update({"state": "arrived"})
    assert replanner.alternative_route(world.a)["available"] is False


def test_alternative_route_live_asks_routes_for_its_first_alternative(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.db.collection("runs").document(world.a).update({"scenario": None, "eta_hospital_s": 500})
    route = Route()
    route.result = {**route_result(), "duration_s": 580.0}
    monkeypatch.setattr(replanner.routes_api, "traffic_to_point", route)
    monkeypatch.setattr(replanner, "offline", lambda: False)
    out = replanner._alternative(world.a)
    assert out["source"] == "routes_alternative" and out["eta_delta_s"] == 80 and out["alt_eta_s"] == 580
    assert out["points"] and route.calls[0]["key"] is None and route.calls[0]["run_id"] == world.a
    assert "points" not in replanner.alternative_route(world.a)
    route.result = {**route_result(), "duration_s": None}  # Routes found nothing
    assert replanner._alternative(world.a)["available"] is False
    world.db.collection("runs").document(world.a).update({"eta_hospital_s": None})
    route.result = route_result()
    assert replanner._alternative(world.a)["available"] is False  # no current ETA to compare with
    monkeypatch.setattr(replanner, "offline", lambda: True)
    assert replanner._alternative(world.a)["available"] is False


def test_live_reroute_stores_an_override_without_points(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.db.collection("runs").document(world.a).update({"scenario": None, "eta_hospital_s": 500})
    route = Route()
    route.result = {**route_result(), "duration_s": 540.0}
    monkeypatch.setattr(replanner.routes_api, "traffic_to_point", route)
    install(monkeypatch, script(plan("reroute", world.a), world.jid))
    assert world.run()["action_text"] == "Rerouted via the alternative route (+40 s)"
    ov = world.run_doc(world.a)["route_override"]
    assert ov["source"] == "routes_alternative" and "points" not in ov


def test_notify_control_writes_an_audit_entry_only(world: World) -> None:
    out = replanner.notify_control("x" * 500, NS(state={"junction_id": world.jid}))
    assert out == {"ok": True}
    (n,) = world.audit("notify_control")
    assert n["junction_id"] == world.jid and len(n["text"]) == 300
    assert replanner.notify_control("hello")["ok"] and world.audit("notify_control")[1]["junction_id"] is None


def test_the_agent_runs_on_the_text_model_with_the_four_tools() -> None:
    assert replanner.TIMEOUT_S == 40
    agent = replanner.corridor_replanner
    assert agent is not None and agent.name == "corridor_replanner"
    assert [t.__name__ for t in agent.tools] == [  # type: ignore[union-attr]
        "junction_state",
        "alternative_route",
        "resequence_options",
        "notify_control",
    ]
    assert agent.model == main.agent.router_model()


# ---- route_override in /location ----------------------------------------------------------------------------------------


def live_run(client: TestClient, db: FakeFirestore, **extra: Any) -> str:
    rid = start(client)
    db.collection("runs").document(rid).update({"destination": BLR_HOSPITAL, **extra})
    return rid


def tick(client: TestClient, rid: str, **kw: Any) -> dict:
    r = send_tick(client, rid, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_live_run_with_an_override_follows_the_alternative_route(
    client: TestClient, seeded: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid = live_run(client, seeded)
    route = Route()
    monkeypatch.setattr(main.routes_api, "traffic_to_point", route)
    tick(client, rid)
    plain = route.calls[0]
    assert plain["key"] == (rid, "route") and plain["alt"] == 0  # no override: the plain route, as before

    seeded.collection("runs").document(rid).update(
        {"route_override": {"source": "routes_alternative", "eta_delta_s": 30}}
    )
    seen: list[tuple[Any, int]] = []

    def asked(origin: Any, dest: Any, key: Any = None, alt: int = 0, **_: Any) -> dict:
        seen.append((key, alt))
        return route.result if alt == 1 else {**route_result(), "duration_s": None, "polyline_points": []}

    monkeypatch.setattr(main.routes_api, "traffic_to_point", asked)
    tick(client, rid)
    assert seen == [((f"{rid}-alt", "route"), 1)]  # its own cache doc, the alternative


def test_an_override_with_no_alternative_left_asks_for_the_plain_route_again(
    client: TestClient, seeded: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid = live_run(client, seeded, route_override={"source": "routes_alternative", "eta_delta_s": 30})
    seen: list[tuple[Any, int]] = []

    def asked(origin: Any, dest: Any, key: Any = None, alt: int = 0, **_: Any) -> dict:
        seen.append((key, alt))
        return {**route_result(), "duration_s": None, "polyline_points": []} if alt else route_result()

    monkeypatch.setattr(main.routes_api, "traffic_to_point", asked)
    out = tick(client, rid)
    assert seen == [((f"{rid}-alt", "route"), 1), ((rid, "route"), 0)] and out["eta_hospital_s"]


def test_a_replay_with_an_override_shifts_its_eta_by_the_alternatives_delta(
    client: TestClient, seeded: FakeFirestore
) -> None:
    rid = start(client, scenario="blr-two-vehicles", source="sim", destination=BLR_HOSPITAL)
    base = tick(client, rid)["eta_hospital_s"]
    seeded.collection("runs").document(rid).update(
        {"route_override": {"source": "scenario_file", "eta_delta_s": 45}}
    )
    assert tick(client, rid)["eta_hospital_s"] == base + 45
