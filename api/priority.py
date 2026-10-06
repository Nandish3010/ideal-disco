"""Deterministic junction sequencing. Rules decide; Gemini only explains."""

import re

import acuity
from telemetry import traced

# ponytail: config, lowest rank passes first. Tune from report cards.
TIER_RANK = {
    "fire_with_trapped": 0,
    "ambulance_critical": 1,
    "fire": 2,
    "ambulance_urgent": 3,
    "police_with_incident": 4,
    "ambulance_stable": 5,
}
GAP_S = 12  # ponytail: fixed gap between vehicles, derive from queue length later
PLATOON_S = 45  # vehicles on the same approach arriving this close together share one green slot


def key(c: dict) -> str:
    t = c["tier"]
    return t if t in TIER_RANK else f"{c['vehicle_type']}_{t}"


def rank(c: dict) -> int:
    """Lower passes first; an unknown tier ranks last."""
    return TIER_RANK.get(key(c), len(TIER_RANK))


def contender(run_id, r, eta_s, approach):
    """Priority-engine row if this run may preempt, else None. Ambulances need the crew's confirmed tier and a patient on
    board; fire and police need an incident (always true for a started run)."""
    vt = r["vehicle_type"]
    if vt == "ambulance":
        if not (r.get("confirmed_tier") and r.get("patient_on_board")):
            return None
        tier = r["confirmed_tier"]
    elif r.get("incident_id"):
        tier = r.get("confirmed_tier") or acuity.tier({"incident_id": r["incident_id"]}, vt)
    else:
        return None
    return {"run_id": run_id, "vehicle_type": vt, "tier": tier, "eta_s": eta_s, "approach": approach}


@traced("priority")
def sequence(contenders: list[dict]) -> list[dict]:
    """contenders: [{run_id, vehicle_type, tier, eta_s, approach}] -> same dicts sorted, each with offset_s. A vehicle on the
    same approach as a slot's leader, within PLATOON_S of the leader's eta, takes the leader's offset (no extra gap)."""
    ordered = sorted(contenders, key=lambda c: (TIER_RANK.get(key(c), len(TIER_RANK)), c["eta_s"]))
    slots: list[tuple[dict, int]] = []  # (leader, offset_s)
    out: list[dict] = []
    for c in ordered:
        slot = next(
            (
                s
                for s in slots
                if c.get("approach")
                and s[0].get("approach") == c["approach"]
                and abs(c["eta_s"] - s[0]["eta_s"]) <= PLATOON_S
            ),
            None,
        )
        if slot is None:
            slot = (c, len(slots) * GAP_S)
            slots.append(slot)
        out.append({**c, "offset_s": slot[1]})
    return out


def spread_s(seq: list[dict]) -> float:
    """Seconds between the first and last arrival in the last slot: the phase must stay green that much longer."""
    last = [c["eta_s"] for c in seq if c["offset_s"] == seq[-1]["offset_s"]]
    return max(last) - min(last)


def rationale_facts(seq: list[dict]) -> list[dict]:
    """The rule-ordered `sequence` as meaning-attached facts for the explanation. reason_code says why a slot sits where it
    does against its neighbour (slot 0: why it beats the next vehicle; later slots: why they follow the one before):
    platoon_shared_approach (same green slot), higher_tier (the tiers differ), else earlier_eta_same_tier."""
    facts = []
    for i, c in enumerate(seq):
        o = seq[i - 1] if i else seq[i + 1] if len(seq) > 1 else c
        if o is c:
            code = "earlier_eta_same_tier"
        elif o["offset_s"] == c["offset_s"]:
            code = "platoon_shared_approach"
        elif TIER_RANK.get(key(o), len(TIER_RANK)) != TIER_RANK.get(key(c), len(TIER_RANK)):
            code = "higher_tier"
        else:
            code = "earlier_eta_same_tier"
        facts.append(
            {
                "vehicle_type": c["vehicle_type"],
                "tier": c["tier"],
                "approach": c.get("approach"),
                "eta_s": round(c["eta_s"]),
                "offset_s": c["offset_s"],
                "reason_code": code,
                "offset_s_is_gap_assigned_by_rules": True,
            }
        )
    return facts


ARRIVAL_WORDS = re.compile(r"arriv|reach|earlier|sooner|first to get|ahead of time", re.I)
VEHICLE_WORDS = re.compile(r"\b(fire|ambulance|police)\b", re.I)
MAX_RATIONALE = 200


def valid_paraphrase(text: str, template: str) -> bool:
    """A model rewrite of `template` is kept only if it is plain prose (no code token such as higher_tier), under
    MAX_RATIONALE chars, names the same vehicle types in the same order as the template, uses no digit the template does
    not, and gives arrival timing only when the template does."""
    order = lambda t: list(dict.fromkeys(w.lower() for w in VEHICLE_WORDS.findall(t)))  # noqa: E731
    return bool(
        text.strip()
        and len(text) < MAX_RATIONALE
        and not re.search(r"[_`{}\[\]<>]", text)
        and order(text) == order(template)
        and set(re.findall(r"\d+", text)) <= set(re.findall(r"\d+", template))
        and (ARRIVAL_WORDS.search(template) or not ARRIVAL_WORDS.search(text))
    )


NAMES = {"ambulance": "Ambulance", "fire": "Fire engine", "police": "Police vehicle"}
REASONS = {
    "higher_tier": "higher priority tier",
    "earlier_eta_same_tier": "same tier, earlier arrival",
    "platoon_shared_approach": "same approach, shared green",
}


def template_rationale(facts: list[dict]) -> str:
    """The stored explanation: first vehicle and why, then each later vehicle's gap (or shared green). Gemini may only
    rephrase it (gemini.paraphrase_sequence, checked by valid_paraphrase)."""

    def name(f: dict) -> str:
        return NAMES[f["vehicle_type"]] + (
            " with trapped persons" if f["tier"] == "fire_with_trapped" else ""
        )

    out = [f"{name(facts[0])} goes first: {REASONS[facts[0]['reason_code']]}."]
    for f, prev in zip(facts[1:], facts, strict=False):
        shared = f["offset_s"] == prev["offset_s"]
        out.append(
            f"{name(f)} shares the green." if shared else f"{name(f)} follows {f['offset_s']} s later."
        )
    return " ".join(out)


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
    assert [c["offset_s"] for c in sequence([amb, {**amb, "run_id": "b"}])] == [
        0,
        12,
    ]  # no approach known: never grouped
    facts = rationale_facts(sequence([amb, fire]))
    want = template_rationale(facts)
    assert (
        want
        == "Fire engine with trapped persons goes first: higher priority tier. Ambulance follows 12 s later."
    )
    assert valid_paraphrase("The fire engine goes first, then the ambulance 12 s later.", want)
    assert not valid_paraphrase("The ambulance goes first because of higher_tier.", want)
    print("priority ok")
