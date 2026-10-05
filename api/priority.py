"""Deterministic junction sequencing. Rules decide; Gemini only explains."""

# ponytail: config, lowest rank passes first. Tune from report cards.
TIER_RANK = {"fire_with_trapped": 0, "ambulance_critical": 1, "fire": 2,
             "ambulance_urgent": 3, "police_with_incident": 4, "ambulance_stable": 5}
GAP_S = 12  # ponytail: fixed gap between vehicles, derive from queue length later
PLATOON_S = 45  # vehicles on the same approach arriving this close together share one green slot


def key(c: dict) -> str:
    t = c["tier"]
    return t if t in TIER_RANK else f"{c['vehicle_type']}_{t}"


def sequence(contenders: list[dict]) -> list[dict]:
    """contenders: [{run_id, vehicle_type, tier, eta_s, approach}] -> same dicts sorted, each with offset_s. A vehicle on the
    same approach as a slot's leader, within PLATOON_S of the leader's eta, takes the leader's offset (no extra gap)."""
    ordered = sorted(contenders, key=lambda c: (TIER_RANK.get(key(c), len(TIER_RANK)), c["eta_s"]))
    slots, out = [], []  # slots: (leader, offset_s)
    for c in ordered:
        slot = next((s for s in slots if c.get("approach") and s[0].get("approach") == c["approach"]
                     and abs(c["eta_s"] - s[0]["eta_s"]) <= PLATOON_S), None)
        if slot is None:
            slot = (c, len(slots) * GAP_S)
            slots.append(slot)
        out.append({**c, "offset_s": slot[1]})
    return out


def spread_s(seq: list[dict]) -> float:
    """Seconds between the first and last arrival in the last slot: the phase must stay green that much longer."""
    last = [c["eta_s"] for c in seq if c["offset_s"] == seq[-1]["offset_s"]]
    return max(last) - min(last)


if __name__ == "__main__":
    fire = {"run_id": "f", "vehicle_type": "fire", "tier": "fire_with_trapped", "eta_s": 90}
    amb = {"run_id": "a", "vehicle_type": "ambulance", "tier": "critical", "eta_s": 30}
    out = sequence([amb, fire])
    assert [c["run_id"] for c in out] == ["f", "a"] and [c["offset_s"] for c in out] == [0, 12]
    near = {**amb, "run_id": "near", "eta_s": 20}
    far = {**amb, "run_id": "far", "eta_s": 60}
    assert [c["run_id"] for c in sequence([far, near])] == ["near", "far"]
    assert sequence([]) == []
    # platoon: same approach within 45 s shares a slot; a different approach, or 46 s apart, gets its own
    a1 = {**amb, "run_id": "a1", "approach": "E", "eta_s": 17}
    a2 = {**amb, "run_id": "a2", "tier": "urgent", "approach": "E", "eta_s": 44}
    f = {**fire, "run_id": "f", "approach": "S", "eta_s": 15}
    out = sequence([a2, a1])
    assert [c["offset_s"] for c in out] == [0, 0] and spread_s(out) == 27
    out = sequence([a2, a1, f])
    assert [(c["run_id"], c["offset_s"]) for c in out] == [("f", 0), ("a1", 12), ("a2", 12)]
    assert [c["offset_s"] for c in sequence([{**a1, "approach": "E"}, {**a2, "approach": "NE"}])] == [0, 12]
    assert [c["offset_s"] for c in sequence([a1, {**a2, "eta_s": 63}])] == [0, 12]
    assert [c["offset_s"] for c in sequence([amb, {**amb, "run_id": "b"}])] == [0, 12]  # no approach known: never grouped
    print("priority ok")
