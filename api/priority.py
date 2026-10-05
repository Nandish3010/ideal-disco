"""Deterministic junction sequencing. Rules decide; Gemini only explains."""

# ponytail: config, lowest rank passes first. Tune from report cards.
TIER_RANK = {"fire_with_trapped": 0, "ambulance_critical": 1, "fire": 2,
             "ambulance_urgent": 3, "police_with_incident": 4, "ambulance_stable": 5}
GAP_S = 12  # ponytail: fixed gap between vehicles, derive from queue length later


def key(c: dict) -> str:
    t = c["tier"]
    return t if t in TIER_RANK else f"{c['vehicle_type']}_{t}"


def sequence(contenders: list[dict]) -> list[dict]:
    """contenders: [{run_id, vehicle_type, tier, eta_s}] -> same dicts sorted, each with offset_s."""
    ordered = sorted(contenders, key=lambda c: (TIER_RANK.get(key(c), len(TIER_RANK)), c["eta_s"]))
    return [{**c, "offset_s": i * GAP_S} for i, c in enumerate(ordered)]


if __name__ == "__main__":
    fire = {"run_id": "f", "vehicle_type": "fire", "tier": "fire_with_trapped", "eta_s": 90}
    amb = {"run_id": "a", "vehicle_type": "ambulance", "tier": "critical", "eta_s": 30}
    out = sequence([amb, fire])
    assert [c["run_id"] for c in out] == ["f", "a"] and [c["offset_s"] for c in out] == [0, 12]
    near = {**amb, "run_id": "near", "eta_s": 20}
    far = {**amb, "run_id": "far", "eta_s": 60}
    assert [c["run_id"] for c in sequence([far, near])] == ["near", "far"]
    assert sequence([]) == []
    print("priority ok")
