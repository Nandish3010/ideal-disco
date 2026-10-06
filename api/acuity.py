"""Deterministic acuity lookup. Gemini extracts fields; this decides the tier. Never an LLM score."""

CRITICAL_CATEGORIES = {"chest_pain", "stroke_signs", "major_bleeding", "unconscious", "seizure"}
URGENT_CATEGORIES = {"moderate_bleeding", "breathing_difficulty", "fracture"}
AIRWAY_WORDS = ("face", "facial", "airway", "inhalation")  # burns near the airway are critical at any size
BREATHING_WORDS = ("breath", "wheez", "throat", "airway", "swell")  # allergic reaction with an airway sign
# Fallback when complaint_category is missing or "other": the old phrase match on the free-text complaint.
CRITICAL_COMPLAINTS = {"chest pain", "stroke signs", "major bleeding", "burns > 20%"}
URGENT_COMPLAINTS = {"fracture", "moderate bleeding", "breathing difficulty"}
# ponytail: complaints match by substring ("chest pain radiating to left arm"); fixed adult ranges, per-age ranges if paediatrics matter
NORMAL = {
    "sbp": (90, 180),
    "dbp": (50, 110),
    "hr": (50, 110),
    "spo2": (94, 100),
    "rr": (10, 24),
    "temp": (36.0, 38.5),
}


def _category_tier(fields: dict, complaint: str) -> str | None:
    """critical / urgent / "" (stable by category) from complaint_category, None when it can't decide."""
    cat = fields.get("complaint_category")
    if cat is None or cat == "other":
        return None
    if cat in CRITICAL_CATEGORIES or fields.get("bleeding_severity") == "major":
        return "critical"
    if cat == "allergic_reaction" and (
        fields.get("breathing") is False or any(w in complaint for w in BREATHING_WORDS)
    ):
        return "critical"
    if cat == "burns":
        pct = fields.get("burn_percent")
        return "critical" if (pct or 0) >= 20 or any(w in complaint for w in AIRWAY_WORDS) else "urgent"
    if cat in URGENT_CATEGORIES or fields.get("bleeding_severity") == "moderate":
        return "urgent"
    # allergic_reaction without an airway sign, abdominal_pain, minor_injury: only the vitals can raise these
    return ""


def tier(fields: dict, vehicle_type: str) -> str:
    if vehicle_type == "fire":
        return "fire_with_trapped" if (fields.get("trapped_persons") or 0) > 0 else "fire"
    if vehicle_type == "police":
        return "police_with_incident" if fields.get("incident_id") else "police"
    complaint = (fields.get("complaint") or "").lower()
    v = fields.get("vitals") or {}
    by_cat = _category_tier(fields, complaint)
    if (
        fields.get("conscious") is False
        or fields.get("breathing") is False
        or (v.get("sbp") is not None and v["sbp"] < 90)
        or (v.get("spo2") is not None and v["spo2"] < 90)
        or by_cat == "critical"
        or (by_cat is None and any(c in complaint for c in CRITICAL_COMPLAINTS))
        or (fields.get("trapped_persons") or 0) > 0
    ):
        return "critical"
    if (
        by_cat == "urgent"
        or (by_cat is None and any(c in complaint for c in URGENT_COMPLAINTS))
        or any(v.get(k) is not None and not lo <= v[k] <= hi for k, (lo, hi) in NORMAL.items())
    ):
        return "urgent"
    return "stable"


if __name__ == "__main__":
    assert tier({"conscious": False}, "ambulance") == "critical"
    assert tier({"vitals": {"spo2": 85}}, "ambulance") == "critical"
    assert tier({"complaint": "Chest pain"}, "ambulance") == "critical"
    assert tier({"complaint": "chest pain radiating to left arm"}, "ambulance") == "critical"
    assert tier({"vitals": {"hr": 130}}, "ambulance") == "urgent"
    assert tier({"complaint": "fracture"}, "ambulance") == "urgent"
    assert (
        tier(
            {
                "complaint": "headache",
                "conscious": True,
                "breathing": True,
                "vitals": {"sbp": 120, "hr": 80, "spo2": 98},
            },
            "ambulance",
        )
        == "stable"
    )
    assert tier({"trapped_persons": 2}, "fire") == "fire_with_trapped"
    assert tier({"trapped_persons": 0}, "fire") == "fire"
    assert tier({"incident_id": "INC-1"}, "police") == "police_with_incident"
    assert (
        tier({"complaint_category": "stroke_signs", "complaint": "facial drooping"}, "ambulance")
        == "critical"
    )
    assert tier({"complaint_category": "burns", "burn_percent": 25}, "ambulance") == "critical"
    assert tier({"complaint_category": "moderate_bleeding"}, "ambulance") == "urgent"
    print("acuity ok")
