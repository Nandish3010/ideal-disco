"""Hospital routing: the deterministic parts (baseline, guards, fallback) and route() driven by a scripted fake of the
ADK runner. The model and Vertex are never called."""

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace as NS
from typing import Any

import pytest

import agent
import hospitals

SILK_BOARD = (12.9172, 77.6229)
JAY, APOLLO, FORTIS = (agent.by_id(i) for i in ("blr_jayadeva", "blr_apollo_bg", "blr_fortis_bg"))


def need(complaint: str, **fields: object) -> list[str]:
    return agent.required_capabilities("critical", {"complaint": complaint, **fields})["required"]


def test_required_capabilities() -> None:
    assert need("chest pain radiating to left arm") == ["cath_lab"]
    assert need("stroke signs") == ["stroke_unit"]
    assert need("burns > 20%") == ["burns"]
    assert need("headache") == []
    assert need("fracture", age=40) == ["trauma"]
    assert need("fracture", transcript_en="fracture, 10 year old") == ["paediatrics", "trauma"]
    out = agent.required_capabilities("urgent", {})
    assert out["confirmed_tier"] == "urgent"  # the tier passes through untouched
    chest = agent.required_capabilities("critical", {"complaint": "chest pain and a fracture"})
    assert chest["required"] == ["cath_lab", "trauma"] and chest["critical"] == ["cath_lab"]


def test_roster_has_the_trade_off_fields() -> None:
    for hs in hospitals.HOSPITALS.values():
        for h in hs:
            assert {"beds_available", "diversion", "trauma_level", "cath_lab_door_to_balloon_min"} <= set(h)
            assert (h["cath_lab_door_to_balloon_min"] is not None) == ("cath_lab" in h["capabilities"])


def test_diversion_is_deterministic_and_apollo_only() -> None:
    ids = [f"run-{i}" for i in range(300)]
    flags = [hospitals.on_diversion(APOLLO, i) for i in ids]
    assert flags == [hospitals.on_diversion(APOLLO, i) for i in ids]
    assert 0.2 < sum(flags) / len(flags) < 0.4  # about 30 %
    assert not any(hospitals.on_diversion(JAY, i) for i in ids)
    assert not hospitals.on_diversion(APOLLO, None)  # no incident: the roster flag only
    assert hospitals.on_diversion({**JAY, "diversion": True}, None)


def test_check_diversion_tool() -> None:
    inc = next(i for i in (f"r{n}" for n in range(99)) if hospitals.on_diversion(APOLLO, i))
    ctx = NS(state={"incident_id": inc})
    assert agent.check_diversion("blr_apollo_bg", ctx) == {
        "hospital_id": "blr_apollo_bg",
        "on_diversion": True,
    }
    assert agent.check_diversion("blr_jayadeva", ctx)["on_diversion"] is False
    assert agent.check_diversion("nowhere")["error"] == "unknown_hospital"


def test_fallback_picks_the_nearest_eligible_hospital() -> None:
    run = {"corridor": "blr"}
    assert agent._fallback(run, {"cath_lab"}, SILK_BOARD, "TimeoutError")["hospital_id"] == "blr_jayadeva"
    assert agent._fallback(run, {"trauma", "paediatrics"}, SILK_BOARD, "x")["hospital_id"] == "blr_fortis_bg"
    out = agent._fallback(
        run, {"burns", "stroke_unit"}, SILK_BOARD, "x"
    )  # nobody has both: nearest with a bed
    assert "only the nearest" in out["reasons"][1] and out["trace"] == [{"fallback": "x"}]


def test_fallback_skips_hospitals_without_beds_or_on_diversion(monkeypatch: pytest.MonkeyPatch) -> None:
    roster = [
        {**h, "beds_available": 0 if h["id"] == "blr_jayadeva" else h["beds_available"]}
        for h in agent.HOSPITALS["blr"]
    ]
    monkeypatch.setitem(agent.HOSPITALS, "blr", roster)
    assert (
        agent._fallback({"corridor": "blr"}, {"cath_lab"}, SILK_BOARD, "x")["hospital_id"] == "blr_apollo_bg"
    )
    diverted = [{**h, "diversion": h["id"] == "blr_apollo_bg"} for h in roster]
    monkeypatch.setitem(
        agent.HOSPITALS, "blr", diverted
    )  # Jayadeva full, Apollo diverted: nothing free has a cath lab
    out = agent._fallback({"corridor": "blr"}, {"cath_lab"}, SILK_BOARD, "x")
    assert out["hospital_id"] == "blr_fortis_bg" and "only the nearest" in out["reasons"][1]


def test_fallback_alternatives_say_why_not() -> None:
    out = agent._fallback({"corridor": "blr"}, {"cath_lab"}, SILK_BOARD, "x")
    alts = {a["hospital_id"]: a["why_not"] for a in out["alternatives"]}
    assert out["hospital_id"] == "blr_jayadeva" and set(alts) == {"blr_apollo_bg", "blr_fortis_bg"}
    assert "further" in alts["blr_apollo_bg"] and alts["blr_fortis_bg"] == "lacks cath_lab"
    assert out["confidence"] is None and out["capabilities"] == [
        {"capability": "cath_lab", "reason": "keyword baseline"}
    ]


def answer(**kw: object) -> dict[str, Any]:
    return {
        "capabilities": [{"capability": "cath_lab", "reason": "chest pain, STEMI picture"}],
        "dropped": [],
        "hospital_id": "blr_jayadeva",
        "eta_s": 999,
        "reasons": ["a", "b", "c"],
        "alternatives": [],
        "confidence": 0.8,
        **kw,
    }


def validated(
    final: dict[str, Any], baseline: set[str], trace: list | None = None, incident: str | None = None
) -> dict:
    return agent._validated("```json\n" + json.dumps(final) + "\n```", trace or [], "blr", baseline, incident)


def eta_entry(h: dict, eta: int) -> dict:
    return {
        "tool": "eta_to",
        "args": {"dest_lat": h["lat"], "dest_lng": h["lng"]},
        "result": f"{eta} s, 2.0 km",
    }


def test_validated_takes_the_tool_eta_two_reasons_and_clamps_confidence() -> None:
    out = validated(answer(confidence=7), {"cath_lab"}, [eta_entry(JAY, 312)])
    assert out["eta_s"] == 312 and out["reasons"] == ["a", "b"] and out["destination"] == JAY["name"]
    assert out["confidence"] == 1.0 and out["trace"][-1]["step"] == "capabilities"
    assert validated(answer(), {"cath_lab"})["eta_s"] == 999  # no tool result: the model's number
    assert validated(answer(confidence="high"), {"cath_lab"})["confidence"] is None


def test_validated_accepts_an_added_capability_with_a_reason() -> None:
    caps = [*answer()["capabilities"], {"capability": "icu", "reason": "SpO2 82 % on a ventilator"}]
    out = validated(answer(capabilities=caps), {"cath_lab"})
    assert [c["capability"] for c in out["capabilities"]] == ["cath_lab", "icu"]
    assert "Added to baseline: icu" in out["trace"][-1]["text"]


def test_validated_alternatives_use_tool_etas_and_skip_junk() -> None:
    alts = [
        {"hospital_id": "blr_apollo_bg", "eta_s": 1, "why_not": "on diversion"},
        {"hospital_id": "blr_jayadeva", "eta_s": 5, "why_not": "the chosen one"},
        {"hospital_id": "hyd_continental", "eta_s": 5, "why_not": "other corridor"},
        "junk",
        {"hospital_id": "blr_fortis_bg", "eta_s": 600, "why_not": "no cath lab"},
    ]
    out = validated(answer(alternatives=alts), {"cath_lab"}, [eta_entry(APOLLO, 280)])
    assert out["alternatives"] == [
        {"hospital_id": "blr_apollo_bg", "eta_s": 280, "why_not": "on diversion"},
        {"hospital_id": "blr_fortis_bg", "eta_s": 600, "why_not": "no cath lab"},
    ]


@pytest.mark.parametrize(
    ("final", "baseline", "guard"),
    [
        (answer(), {"trauma", "cath_lab"}, "unjustified_deviation"),  # drops trauma without a reason
        (answer(capabilities=[]), {"cath_lab"}, "dropped_baseline_capability"),
        (
            answer(capabilities=[{"capability": "icu", "reason": "x"}]),
            {"cath_lab"},
            "dropped_baseline_capability",
        ),
        (
            answer(capabilities=[*answer()["capabilities"], {"capability": "icu", "reason": " "}]),
            {"cath_lab"},
            "unjustified_deviation",
        ),
        (answer(capabilities=[{"capability": "magic", "reason": "x"}]), set(), "unknown_capability"),
        (answer(hospital_id="nowhere", capabilities=[]), set(), "ineligible_choice"),
        (
            answer(hospital_id="hyd_continental", capabilities=[]),
            set(),
            "ineligible_choice",
        ),  # another corridor
        (
            answer(capabilities=[{"capability": "trauma", "reason": "x"}]),
            set(),
            "ineligible_choice",
        ),  # Jayadeva lacks it
    ],
)
def test_validated_guards(final: dict[str, Any], baseline: set[str], guard: str) -> None:
    with pytest.raises(agent.InvalidChoice) as e:
        validated(final, baseline)
    assert e.value.guard == guard


def test_validated_rejects_diverted_and_full_hospitals(monkeypatch: pytest.MonkeyPatch) -> None:
    inc = next(i for i in (f"r{n}" for n in range(99)) if hospitals.on_diversion(APOLLO, i))
    with pytest.raises(agent.InvalidChoice):
        validated(answer(hospital_id="blr_apollo_bg"), {"cath_lab"}, incident=inc)
    monkeypatch.setitem(agent.HOSPITALS, "blr", [{**h, "beds_available": 0} for h in agent.HOSPITALS["blr"]])
    with pytest.raises(agent.InvalidChoice):
        validated(answer(hospital_id="blr_jayadeva"), {"cath_lab"})


# ---- route() with a scripted ADK event stream ----


def call(name: str, **args: object) -> NS:
    return NS(
        function_call=NS(id=f"{name}{len(args)}{hash(str(args)) % 999}", name=name, args=args),
        function_response=None,
        text=None,
    )


def respond(c: NS, response: dict) -> NS:
    return NS(function_call=None, function_response=NS(id=c.function_call.id, response=response), text=None)


def event(*parts: NS, final: bool = False) -> NS:
    return NS(content=NS(parts=list(parts)), is_final_response=lambda: final)


def script_for(final: dict[str, Any], diverted_apollo: bool = False) -> list[NS]:
    """What the model does for a chest-pain call: baseline, hospitals, diversion check on Apollo, ETA for the rest."""
    base = call("required_capabilities", confirmed_tier="critical", fields={})
    div = call("check_diversion", hospital_id="blr_apollo_bg")
    eta = call("eta_to", lat=SILK_BOARD[0], lng=SILK_BOARD[1], dest_lat=JAY["lat"], dest_lng=JAY["lng"])
    return [
        event(base),
        event(respond(base, {"required": ["cath_lab"], "critical": ["cath_lab"]})),
        event(div),
        event(respond(div, {"hospital_id": "blr_apollo_bg", "on_diversion": diverted_apollo})),
        event(eta),
        event(respond(eta, {"eta_s": 410, "distance_km": 2.7})),
        event(NS(function_call=None, function_response=None, text=json.dumps(final)), final=True),
    ]


class FakeSessions:
    state: dict = {}

    async def create_session(self, **kw: Any) -> None:
        FakeSessions.state = kw["state"]


def online(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not offline, but Routes finds nothing, so eta_to takes its straight-line answer without a request."""
    monkeypatch.setattr(agent, "offline", lambda: False)
    monkeypatch.setattr(agent.routes_api, "traffic_to_point", lambda *a, **k: {"duration_s": None})


def install(monkeypatch: pytest.MonkeyPatch, events: list[NS], delay: float = 0) -> None:
    class FakeRunner:
        def __init__(self, **_: object) -> None: ...

        async def run_async(self, **_: object) -> AsyncIterator[NS]:
            for ev in events:
                await asyncio.sleep(delay)
                yield ev

    online(monkeypatch)
    monkeypatch.setattr(agent, "HAVE_ADK", True)
    monkeypatch.setattr(agent, "InMemorySessionService", FakeSessions, raising=False)
    monkeypatch.setattr(agent, "Runner", FakeRunner, raising=False)
    monkeypatch.setattr(agent, "hospital_router", None, raising=False)


CHEST = {
    "corridor": "blr",
    "id": "run-1",
    "confirmed_tier": "critical",
    "fields": {"complaint": "chest pain, sweating"},
}


def test_route_accepts_a_model_added_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    caps = [*answer()["capabilities"], {"capability": "icu", "reason": "hypotensive, may need ventilation"}]
    install(monkeypatch, script_for(answer(capabilities=caps, eta_s=410)))
    r = agent.route(CHEST)
    assert r["hospital_id"] == "blr_jayadeva" and r["eta_s"] == 410 and r["confidence"] == 0.8
    assert [c["capability"] for c in r["capabilities"]] == ["cath_lab", "icu"]
    assert FakeSessions.state == {"incident_id": "run-1"}
    assert "fallback" not in json.dumps(r["trace"]) and "guard" not in json.dumps(r["trace"])
    div = call("check_diversion", hospital_id="blr_apollo_bg").function_call
    assert agent._trace_entry(div, {"on_diversion": False})["text"] == (
        "called check_diversion(Apollo Hospital Bannerghatta Road) → accepting"
    )
    assert any(
        t["tool"] == "check_diversion" and t["result"] == "accepting" for t in r["trace"] if "tool" in t
    )
    assert all(t.get("text") for t in r["trace"])  # the UI renders `text` for every step


def test_route_guards_a_dropped_critical_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, script_for(answer(capabilities=[{"capability": "icu", "reason": "unstable"}])))
    r = agent.route(CHEST)
    assert r["hospital_id"] == "blr_jayadeva" and r["confidence"] is None  # the rule-based pick
    assert r["trace"][-1]["guard"] == "dropped_baseline_capability" and "cath_lab" in r["trace"][-1]["text"]
    assert "safety check" in r["reasons"][0]


def test_route_prefers_a_farther_hospital_when_the_nearer_is_on_diversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roster = [{**h, "diversion": h["id"] == "blr_jayadeva"} for h in agent.HOSPITALS["blr"]]
    monkeypatch.setitem(agent.HOSPITALS, "blr", roster)  # Jayadeva (nearest cath lab) is on diversion
    jay_alt = {"hospital_id": "blr_jayadeva", "eta_s": 410, "why_not": "on diversion"}
    fortis_alt = {"hospital_id": "blr_fortis_bg", "eta_s": 520, "why_not": "no cath lab"}
    final = answer(hospital_id="blr_apollo_bg", eta_s=600, alternatives=[jay_alt, fortis_alt])
    install(monkeypatch, script_for(final))
    r = agent.route(CHEST)
    assert r["hospital_id"] == "blr_apollo_bg" and "guard" not in json.dumps(r["trace"])
    assert [a["hospital_id"] for a in r["alternatives"]] == ["blr_jayadeva", "blr_fortis_bg"]
    assert r["alternatives"][0] == {
        "hospital_id": "blr_jayadeva",
        "eta_s": 410,
        "why_not": "on diversion",
    }  # the tool's ETA


def test_route_guards_a_choice_on_diversion(monkeypatch: pytest.MonkeyPatch) -> None:
    roster = [{**h, "diversion": h["id"] == "blr_jayadeva"} for h in agent.HOSPITALS["blr"]]
    monkeypatch.setitem(agent.HOSPITALS, "blr", roster)
    install(monkeypatch, script_for(answer()))  # the model still picks Jayadeva
    r = agent.route(CHEST)
    assert r["hospital_id"] == "blr_apollo_bg" and r["trace"][-1]["guard"] == "ineligible_choice"
    assert (
        r["alternatives"][0]["why_not"] == "on diversion" or r["alternatives"][1]["why_not"] == "on diversion"
    )


def test_route_times_out_into_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, script_for(answer()), delay=0.2)
    monkeypatch.setattr(agent, "TIMEOUT_S", 0.05)
    r = agent.route(CHEST)
    assert r["hospital_id"] == "blr_jayadeva" and r["trace"] == [{"fallback": "TimeoutError"}]


def test_route_bad_json_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = script_for(answer())
    ev[-1] = event(NS(function_call=None, function_response=None, text="not json"), final=True)
    install(monkeypatch, ev)
    assert agent.route(CHEST)["trace"] == [{"fallback": "JSONDecodeError"}]


def test_route_without_adk_is_the_rule_based_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    online(monkeypatch)
    monkeypatch.setattr(agent, "HAVE_ADK", False)
    r = agent.route(CHEST)
    assert r["hospital_id"] == "blr_jayadeva" and r["trace"] == [{"fallback": "adk_missing"}]


def test_route_offline_is_the_rule_based_fallback() -> None:
    r = agent.route({"corridor": "blr", "confirmed_tier": "critical", "fields": {"complaint": "chest pain"}})
    assert r["hospital_id"] == "blr_jayadeva" and r["trace"] == [{"fallback": "offline_ai"}]
    assert set(r) >= {"alternatives", "confidence", "capabilities"}


def test_eta_to_offline_is_a_straight_line() -> None:
    out = agent.eta_to(12.9172, 77.6229, 12.9185, 77.599)
    assert out["source"] == "straight_line_estimate" and out["eta_s"] > 0 and out["distance_km"] > 2


def test_router_model_follows_gemini_text_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent runs on GEMINI_TEXT_MODEL (the README's setting); GEMINI_MODEL is the extraction model and is ignored."""
    monkeypatch.delenv("GEMINI_TEXT_MODEL", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "extraction-model")
    assert agent.router_model() == "gemini-3-flash-preview"
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "text-model")
    assert agent.router_model() == "text-model"
