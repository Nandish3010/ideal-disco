from priority import (
    GAP_S,
    PLATOON_S,
    rationale_facts,
    sequence,
    spread_s,
    template_rationale,
    valid_rationale,
)

FIRE = {"run_id": "f", "vehicle_type": "fire", "tier": "fire_with_trapped", "eta_s": 90}
AMB = {"run_id": "a", "vehicle_type": "ambulance", "tier": "critical", "eta_s": 30}


def offsets(seq: list[dict]) -> list[tuple[str, int]]:
    return [(c["run_id"], c["offset_s"]) for c in seq]


def test_empty_and_single() -> None:
    assert sequence([]) == []
    assert offsets(sequence([AMB])) == [("a", 0)]


def test_tier_rank_beats_eta() -> None:
    out = sequence([AMB, FIRE])  # the fire engine arrives later but ranks first
    assert offsets(out) == [("f", 0), ("a", GAP_S)]


def test_same_rank_orders_by_eta() -> None:
    near, far = {**AMB, "run_id": "near", "eta_s": 20}, {**AMB, "run_id": "far", "eta_s": 60}
    assert [c["run_id"] for c in sequence([far, near])] == ["near", "far"]


def test_ambulance_tiers_rank_between_fire_and_police() -> None:
    urgent = {**AMB, "run_id": "u", "tier": "urgent"}
    police = {"run_id": "p", "vehicle_type": "police", "tier": "police_with_incident", "eta_s": 10}
    stable = {**AMB, "run_id": "s", "tier": "stable", "eta_s": 5}
    order = [c["run_id"] for c in sequence([stable, police, urgent, AMB, FIRE])]
    assert order == ["f", "a", "u", "p", "s"]


def test_unknown_tier_goes_last() -> None:
    odd = {**AMB, "run_id": "odd", "tier": "mystery", "eta_s": 1}
    assert [c["run_id"] for c in sequence([odd, AMB])] == ["a", "odd"]


def test_no_approach_never_grouped() -> None:
    out = sequence([AMB, {**AMB, "run_id": "b"}])
    assert [c["offset_s"] for c in out] == [0, GAP_S]


def test_platoon_same_approach_shares_offset() -> None:
    a1 = {**AMB, "run_id": "a1", "approach": "E", "eta_s": 17}
    a2 = {**AMB, "run_id": "a2", "tier": "urgent", "approach": "E", "eta_s": 44}
    out = sequence([a2, a1])
    assert [c["offset_s"] for c in out] == [0, 0]
    assert spread_s(out) == 27


def test_platoon_boundary() -> None:
    a1 = {**AMB, "run_id": "a1", "approach": "E", "eta_s": 17}
    on_edge = {**AMB, "run_id": "a2", "approach": "E", "eta_s": 17 + PLATOON_S}
    past_edge = {**on_edge, "eta_s": 17 + PLATOON_S + 1}
    assert [c["offset_s"] for c in sequence([a1, on_edge])] == [0, 0]
    assert [c["offset_s"] for c in sequence([a1, past_edge])] == [0, GAP_S]


def test_different_approach_gets_its_own_slot() -> None:
    a1 = {**AMB, "run_id": "a1", "approach": "E", "eta_s": 17}
    a2 = {**AMB, "run_id": "a2", "tier": "urgent", "approach": "E", "eta_s": 44}
    f = {**FIRE, "approach": "S", "eta_s": 15}
    assert offsets(sequence([a2, a1, f])) == [("f", 0), ("a1", GAP_S), ("a2", GAP_S)]
    other = {**a2, "approach": "NE"}
    assert [c["offset_s"] for c in sequence([a1, other])] == [0, GAP_S]


def test_spread_is_within_the_last_slot_only() -> None:
    f = {**FIRE, "approach": "S", "eta_s": 100}
    a1 = {**AMB, "run_id": "a1", "approach": "E", "eta_s": 10}
    a2 = {**AMB, "run_id": "a2", "approach": "E", "eta_s": 35}
    assert spread_s(sequence([f, a1, a2])) == 25
    assert spread_s(sequence([AMB])) == 0


# ---- grounded rationale -----------------------------------------------------------------------------------------------


def test_facts_attach_meaning_to_the_order() -> None:
    near = {**AMB, "run_id": "n", "eta_s": 10}
    facts = rationale_facts(sequence([AMB, FIRE]))
    assert [f["reason_code"] for f in facts] == ["higher_tier", "higher_tier"]
    assert facts[0] == {
        "vehicle_type": "fire",
        "tier": "fire_with_trapped",
        "approach": None,
        "eta_s": 90,
        "offset_s": 0,
        "reason_code": "higher_tier",
        "offset_s_is_gap_assigned_by_rules": True,
    }
    assert [f["reason_code"] for f in rationale_facts(sequence([AMB, near]))] == ["earlier_eta_same_tier"] * 2
    a1 = {**AMB, "run_id": "a1", "approach": "E", "eta_s": 17}
    a2 = {**AMB, "run_id": "a2", "approach": "E", "eta_s": 44}
    assert [f["reason_code"] for f in rationale_facts(sequence([a1, a2]))] == ["platoon_shared_approach"] * 2
    assert (
        rationale_facts(sequence([AMB]))[0]["reason_code"] == "earlier_eta_same_tier"
    )  # alone: nothing to compare


def test_validator_needs_the_first_vehicle_and_only_given_numbers() -> None:
    facts = rationale_facts(sequence([AMB, FIRE]))  # fire first, offsets 0 and 12, etas 90 and 30
    assert valid_rationale("The fire engine goes first because its tier is higher.", facts)
    assert valid_rationale("The fire engine goes first; the ambulance follows 12 s later.", facts)
    assert not valid_rationale("The ambulance goes first.", facts)  # first vehicle not named
    assert not valid_rationale(
        "The fire engine goes first because it arrives 12 seconds earlier than 7 others.", facts
    )
    assert not valid_rationale("The fire engine goes first, 60 seconds ahead.", facts)  # a number nobody gave
    assert not valid_rationale(
        "The fire engine goes first because it arrives 12 seconds earlier.", facts
    )  # false cause
    assert not valid_rationale("  ", facts)
    near = {**AMB, "run_id": "n", "eta_s": 10}
    same = rationale_facts(sequence([AMB, near]))  # equal tiers: arrival time is the real reason here
    assert valid_rationale("The ambulance with the earlier arrival goes first.", same)


def test_template_sentence_is_deterministic() -> None:
    facts = rationale_facts(sequence([AMB, FIRE]))
    want = "Fire engine with trapped persons goes first: higher priority tier. Ambulance follows 12 s later."
    assert template_rationale(facts) == want and valid_rationale(want, facts)
    a1 = {**AMB, "run_id": "a1", "approach": "E", "eta_s": 17}
    a2 = {**AMB, "run_id": "a2", "approach": "E", "eta_s": 44}
    pol = {"run_id": "p", "vehicle_type": "police", "tier": "police_with_incident", "eta_s": 80}
    got = template_rationale(rationale_facts(sequence([a1, a2, pol])))
    assert (
        got
        == "Ambulance goes first: same approach, shared green. Ambulance shares the green. Police vehicle follows 12 s later."
    )
