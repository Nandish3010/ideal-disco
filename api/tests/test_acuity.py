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
