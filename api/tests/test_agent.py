"""Hospital routing: the deterministic parts (capabilities, validation, fallback). The ADK agent itself is never called."""

import json

import pytest

import agent

SILK_BOARD = (12.9172, 77.6229)


def need(complaint: str, **fields: object) -> list[str]:
    return agent.required_capabilities("critical", {"complaint": complaint, **fields})["required"]


def test_required_capabilities() -> None:
    assert need("chest pain radiating to left arm") == ["cath_lab"]
    assert need("stroke signs") == ["stroke_unit"]
    assert need("burns > 20%") == ["burns"]
    assert need("headache") == []
    assert need("fracture", age=40) == ["trauma"]
    assert need("fracture", transcript_en="fracture, 10 year old") == ["paediatrics", "trauma"]
    assert (
        agent.required_capabilities("urgent", {})["confirmed_tier"] == "urgent"
    )  # the tier passes through untouched


def test_fallback_picks_the_nearest_eligible_hospital() -> None:
    run = {"corridor": "blr"}
    assert agent._fallback(run, {"cath_lab"}, SILK_BOARD, "TimeoutError")["hospital_id"] == "blr_jayadeva"
    assert agent._fallback(run, {"trauma", "paediatrics"}, SILK_BOARD, "x")["hospital_id"] == "blr_fortis_bg"
    out = agent._fallback(
        run, {"burns", "stroke_unit"}, SILK_BOARD, "x"
    )  # nobody has both: nearest with a bed
    assert "only the nearest" in out["reasons"][1] and out["trace"] == [{"fallback": "x"}]


def test_fallback_skips_hospitals_without_beds(monkeypatch: pytest.MonkeyPatch) -> None:
    roster = [
        {**h, "beds_available": 0 if h["id"] == "blr_jayadeva" else h["beds_available"]}
        for h in agent.HOSPITALS["blr"]
    ]
    monkeypatch.setitem(agent.HOSPITALS, "blr", roster)
    assert (
        agent._fallback({"corridor": "blr"}, {"cath_lab"}, SILK_BOARD, "x")["hospital_id"] == "blr_apollo_bg"
    )


def answer(**kw: object) -> str:
    return json.dumps({"hospital_id": "blr_jayadeva", "eta_s": 999, "reasons": ["a", "b", "c"], **kw})


def test_validated_takes_the_tool_eta_and_two_reasons() -> None:
    h = agent.by_id("blr_jayadeva")
    trace = [{"tool": "eta_to", "args": {"dest_lat": h["lat"], "dest_lng": h["lng"]}, "result": "312 s"}]
    out = agent._validated("```json\n" + answer() + "\n```", trace, "blr", {"cath_lab"})
    assert out["eta_s"] == 312 and out["reasons"] == ["a", "b"] and out["destination"] == h["name"]
    assert agent._validated(answer(), [], "blr", set())["eta_s"] == 999  # no tool result: the model's number


@pytest.mark.parametrize(
    ("final", "needed"),
    [
        (answer(), {"trauma"}),  # lacks a required capability
        (answer(hospital_id="nowhere"), set()),
        (answer(hospital_id="hyd_continental"), set()),  # another corridor's hospital
    ],
)
def test_validated_rejects_ineligible_choices(final: str, needed: set[str]) -> None:
    with pytest.raises(agent.InvalidChoice):
        agent._validated(final, [], "blr", needed)


def test_route_offline_is_the_rule_based_fallback() -> None:
    r = agent.route({"corridor": "blr", "confirmed_tier": "critical", "fields": {"complaint": "chest pain"}})
    assert r["hospital_id"] == "blr_jayadeva" and r["trace"] == [{"fallback": "offline_ai"}]


def test_eta_to_offline_is_a_straight_line() -> None:
    out = agent.eta_to(12.9172, 77.6229, 12.9185, 77.599)
    assert out["source"] == "straight_line_estimate" and out["eta_s"] > 0
