"""Fixes from the clean run: fire dispatch extraction, last multi-vehicle sequence, route guard."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agent
import gemini
import main
from fakefs import FakeFirestore
from signal_adapter import SimAdapter
from test_api import FIRE, assert_envelope, run_doc, start

# ---- fire dispatch extraction -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("structure fire, 2 people trapped", 2),
        ("Warehouse fire. One person trapped on the first floor", 1),
        ("three persons are trapped", 3),
        ("structure fire, no one trapped", 0),
        ("kitchen fire, nobody trapped", 0),
        ("vehicle fire on the flyover", None),
        ("", None),
    ],
)
def test_trapped_persons_fallback(text: str, want: int | None) -> None:
    assert gemini.trapped_from_text(text) == want


def test_offline_fire_note_is_read_by_the_stub(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client, FIRE)
    r = client.post("/triage", json={"run_id": rid, "text": "structure fire, 2 people trapped"})
    assert r.status_code == 200, r.text
    assert r.json()["fields"]["trapped_persons"] == 2 and r.json()["suggested_tier"] == "fire_with_trapped"
    r = client.post("/triage", json={"run_id": rid, "text": "structure fire, no one trapped"})
    assert r.json()["fields"]["trapped_persons"] == 0 and r.json()["suggested_tier"] == "fire"


def test_fire_instruction_and_regex_fallback_when_the_model_leaves_it_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Any] = []
    note = "structure fire, 2 people trapped"

    def fake_generate_json(models: list[str], contents: Any, cfg: Any, schema: Any, *a: Any, **k: Any) -> Any:
        seen.append(cfg.system_instruction)
        return gemini.Extraction(transcript_en=note, incident_type="structure fire").model_dump(), "m"

    monkeypatch.setattr(gemini, "offline", lambda: False)
    monkeypatch.setattr(gemini, "generate_json", fake_generate_json)
    monkeypatch.setenv("GEMINI_MODEL", "m")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "m")
    assert gemini.extract(None, None, note, "fire", None)["trapped_persons"] == 2
    assert "dispatch note" in seen[0] and "trapped_persons" in seen[0]
    gemini.extract(None, None, note, "ambulance", None)
    assert "dispatch note" not in seen[1]


# ---- the last multi-vehicle sequence ------------------------------------------------------------------------------------

TWO = [
    {"run_id": "f", "offset_s": 0, "approach": "S"},
    {"run_id": "a", "offset_s": 12, "approach": "E"},
]
ONE = [{"run_id": "a", "offset_s": 0, "approach": "E"}]


def junction(db: FakeFirestore) -> dict:
    return db.collection("junctions").document("blr_j3").get().to_dict() or {}


def test_last_sequence_survives_a_single_vehicle_phase(seeded: FakeFirestore) -> None:
    adapter = SimAdapter(seeded)
    adapter.request_green("blr_j3", "S", 60, ["f", "a"], TWO)
    first = junction(seeded)["last_sequence"]
    assert first["sequence"] == TWO and first["at"] <= datetime.now(UTC)
    adapter.request_green("blr_j3", "E", 30, ["a"], ONE)
    j = junction(seeded)
    assert len(j["phase"]["sequence"]) == 1 and j["last_sequence"] == first
    adapter.request_green("blr_j3", "E", 30, [], None)
    assert junction(seeded)["last_sequence"] == first


def test_rationale_is_kept_with_the_last_sequence_and_never_overwritten_by_one_vehicle(
    seeded: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "offline", lambda: False)
    monkeypatch.setattr(main, "translate", lambda text, lang: f"[{lang}] {text}")
    monkeypatch.setattr(main.gemini, "paraphrase_sequence", lambda s, f: "")  # rejected: the template lands
    rows = [
        {
            "run_id": "f",
            "vehicle_type": "fire",
            "tier": "fire_with_trapped",
            "eta_s": 90,
            "approach": "S",
            "offset_s": 0,
        },
        {
            "run_id": "a",
            "vehicle_type": "ambulance",
            "tier": "critical",
            "eta_s": 95,
            "approach": "E",
            "offset_s": 12,
        },
    ]
    SimAdapter(seeded).request_green("blr_j3", "S", 60, ["f", "a"], TWO)
    main.rationale("blr_j3", rows, "kn")
    ls = junction(seeded)["last_sequence"]
    assert ls["rationale"] and ls["rationale_local"] == "[kn] " + ls["rationale"]
    assert junction(seeded)["phase"]["rationale"] == ls["rationale"]
    SimAdapter(seeded).request_green("blr_j3", "E", 30, ["a"], ONE)
    main.rationale("blr_j3", rows[1:], "kn")
    j = junction(seeded)
    assert "rationale" not in j["phase"] and j["last_sequence"] == ls


# ---- POST /route ---------------------------------------------------------------------------------------------------------


def test_route_is_409_for_arrived_and_ended_runs(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client)
    client.post(f"/runs/{rid}/confirm", json={"tier": "critical"})
    assert client.post("/route", json={"run_id": rid}).status_code == 200
    for state in ("arrived", "ended"):
        seeded.collection("runs").document(rid).update({"state": state})
        body = assert_envelope(client.post("/route", json={"run_id": rid}), 409, "run_not_en_route")
        assert "arrived or ended" in body["detail"]
    seeded.collection("runs").document(rid).update({"state": "en_route"})
    assert client.post("/route", json={"run_id": rid}).status_code == 200
    assert run_doc(seeded, rid)["routing"]["hospital_id"]


def test_agent_gives_the_model_40_seconds() -> None:
    assert agent.TIMEOUT_S == 40
