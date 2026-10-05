"""Deterministic acuity lookup. Gemini extracts fields; this decides the tier. Never an LLM score."""

CRITICAL_COMPLAINTS = {"chest pain", "stroke signs", "major bleeding", "burns > 20%"}
URGENT_COMPLAINTS = {"fracture", "moderate bleeding", "breathing difficulty"}
# ponytail: fixed adult ranges, per-age ranges if paediatrics matter
NORMAL = {"sbp": (90, 180), "dbp": (50, 110), "hr": (50, 110), "spo2": (94, 100), "rr": (10, 24), "temp": (36.0, 38.5)}


def tier(fields: dict, vehicle_type: str) -> str:
    if vehicle_type == "fire":
        return "fire_with_trapped" if (fields.get("trapped_persons") or 0) > 0 else "fire"
    if vehicle_type == "police":
        return "police_with_incident" if fields.get("incident_id") else "police"
    complaint = (fields.get("complaint") or "").lower()
    v = fields.get("vitals") or {}
    if (fields.get("conscious") is False or fields.get("breathing") is False
            or (v.get("sbp") is not None and v["sbp"] < 90)
            or (v.get("spo2") is not None and v["spo2"] < 90)
            or complaint in CRITICAL_COMPLAINTS
            or (fields.get("trapped_persons") or 0) > 0):
        return "critical"
    if complaint in URGENT_COMPLAINTS or any(
            v.get(k) is not None and not lo <= v[k] <= hi for k, (lo, hi) in NORMAL.items()):
        return "urgent"
    return "stable"


if __name__ == "__main__":
    assert tier({"conscious": False}, "ambulance") == "critical"
    assert tier({"vitals": {"spo2": 85}}, "ambulance") == "critical"
    assert tier({"complaint": "Chest pain"}, "ambulance") == "critical"
    assert tier({"vitals": {"hr": 130}}, "ambulance") == "urgent"
    assert tier({"complaint": "fracture"}, "ambulance") == "urgent"
    assert tier({"complaint": "headache", "conscious": True, "breathing": True,
                 "vitals": {"sbp": 120, "hr": 80, "spo2": 98}}, "ambulance") == "stable"
    assert tier({"trapped_persons": 2}, "fire") == "fire_with_trapped"
    assert tier({"trapped_persons": 0}, "fire") == "fire"
    assert tier({"incident_id": "INC-1"}, "police") == "police_with_incident"
    print("acuity ok")
