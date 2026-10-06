import pytest

from acuity import tier

AMB = "ambulance"
OK_VITALS = {"sbp": 120, "hr": 80, "spo2": 98}


@pytest.mark.parametrize(
    "fields",
    [
        {"conscious": False},
        {"breathing": False},
        {"vitals": {"sbp": 85}},
        {"vitals": {"spo2": 85}},
        {"complaint": "Chest pain"},
        {"complaint": "chest pain radiating to left arm"},
        {"complaint": "major bleeding"},
        {"trapped_persons": 1},
    ],
)
def test_ambulance_critical(fields: dict) -> None:
    assert tier(fields, AMB) == "critical"


@pytest.mark.parametrize(
    "fields",
    [
        {"complaint": "fracture"},
        {"complaint": "breathing difficulty"},
        {"vitals": {"hr": 130}},
        {"vitals": {"temp": 39.5}},
        {"vitals": {"spo2": 92}},  # below 94 but not below 90
    ],
)
def test_ambulance_urgent(fields: dict) -> None:
    assert tier(fields, AMB) == "urgent"


def test_ambulance_stable_and_empty() -> None:
    assert (
        tier({"complaint": "headache", "conscious": True, "breathing": True, "vitals": OK_VITALS}, AMB)
        == "stable"
    )
    assert tier({}, AMB) == "stable"  # missing values never raise the tier
    assert tier({"vitals": {"sbp": None}}, AMB) == "stable"


def test_critical_beats_urgent() -> None:
    assert tier({"complaint": "fracture", "vitals": {"spo2": 80}}, AMB) == "critical"


def test_fire() -> None:
    assert tier({"trapped_persons": 2}, "fire") == "fire_with_trapped"
    assert tier({"trapped_persons": 0}, "fire") == "fire"
    assert tier({}, "fire") == "fire"


def test_police() -> None:
    assert tier({"incident_id": "INC-1"}, "police") == "police_with_incident"
    assert tier({}, "police") == "police"


@pytest.mark.parametrize(
    "fields,expected",
    [
        ({"complaint_category": "chest_pain"}, "critical"),
        ({"complaint_category": "stroke_signs"}, "critical"),
        ({"complaint_category": "major_bleeding"}, "critical"),
        ({"complaint_category": "unconscious"}, "critical"),
        ({"complaint_category": "seizure"}, "critical"),
        ({"complaint_category": "allergic_reaction", "complaint": "swelling of the throat"}, "critical"),
        ({"complaint_category": "allergic_reaction", "breathing": False}, "critical"),
        ({"complaint_category": "allergic_reaction", "complaint": "hives on arms"}, "stable"),
        ({"complaint_category": "burns", "burn_percent": 25}, "critical"),
        ({"complaint_category": "burns", "burn_percent": 5, "complaint": "burn to the face"}, "critical"),
        ({"complaint_category": "burns", "burn_percent": 10}, "urgent"),
        ({"complaint_category": "burns"}, "urgent"),
        ({"complaint_category": "moderate_bleeding"}, "urgent"),
        ({"complaint_category": "breathing_difficulty"}, "urgent"),
        ({"complaint_category": "fracture"}, "urgent"),
        ({"complaint_category": "abdominal_pain"}, "stable"),
        ({"complaint_category": "abdominal_pain", "vitals": {"hr": 125}}, "urgent"),
        ({"complaint_category": "minor_injury", "vitals": OK_VITALS}, "stable"),
        ({"complaint_category": "minor_injury", "bleeding_severity": "moderate"}, "urgent"),
        ({"complaint_category": "minor_injury", "bleeding_severity": "major"}, "critical"),
        ({"complaint_category": "other"}, "stable"),
        ({"complaint_category": "other", "complaint": "chest pain"}, "critical"),  # falls back to phrases
        ({"complaint_category": None, "complaint": "fracture"}, "urgent"),
        ({"complaint_category": "minor_injury", "vitals": {"spo2": 85}}, "critical"),  # vitals still win
        ({"complaint_category": "minor_injury", "conscious": False}, "critical"),
    ],
)
def test_category(fields: dict, expected: str) -> None:
    assert tier(fields, AMB) == expected


# transcript -> fields as the extractor returns them for the three synthetic-eval misses
EVAL_MISSES = [
    (
        "Stroke alert. 67-year-old male, facial drooping on left, right arm weakness, slurred speech.",
        {"complaint": "facial drooping on left, right arm weakness", "complaint_category": "stroke_signs"},
        "critical",
    ),
    (
        "Burn injury. Thermal burns to chest and arms, approximately 25 percent body surface area.",
        {"complaint": "burn injury to chest and arms", "complaint_category": "burns", "burn_percent": 25},
        "critical",
    ),
    (
        "Laceration to left forearm with moderate bleeding, controlled by direct pressure.",
        {
            "complaint": "laceration to left forearm",
            "complaint_category": "moderate_bleeding",
            "bleeding_severity": "moderate",
        },
        "urgent",
    ),
]


@pytest.mark.parametrize("transcript,fields,expected", EVAL_MISSES, ids=["stroke", "burns", "bleeding"])
def test_eval_misses(transcript: str, fields: dict, expected: str) -> None:
    assert (
        tier({**fields, "conscious": True, "breathing": True, "transcript_en": transcript}, AMB) == expected
    )


def test_category_schema() -> None:
    from gemini import Extraction

    e = Extraction(transcript_en="x", complaint_category="burns", burn_percent=25, bleeding_severity=None)
    assert e.model_dump()["complaint_category"] == "burns"
    assert Extraction(transcript_en="x").complaint_category is None
    with pytest.raises(ValueError):
        Extraction.model_validate({"transcript_en": "x", "complaint_category": "made_up"})
