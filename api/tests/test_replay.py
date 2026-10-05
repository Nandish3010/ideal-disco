"""Plays data/scenarios/blr-two-vehicles.json through the API, all three vehicles interleaved by scenario time, no sleeping
(the in-process version of api/offline_replay.py). The drive runs once; the tests read what it recorded."""

from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

import main
from conftest import fake
from corridor import CORRIDORS, SCENARIOS
from fakefs import seed

NAME = "blr-two-vehicles"
SC, BLR = SCENARIOS[NAME], CORRIDORS["blr"]
ORDER = [f"blr_{j['id']}" for j in BLR["junctions"]]


def collect(coll: Any) -> list[dict]:
    return [d.to_dict() for d in coll.stream()]


@pytest.fixture(scope="module")
def replay() -> Iterator[dict[str, dict]]:
    """{tier: per-run record}, plus the audit trail under "audit"."""
    fake.clear()
    seed(fake)
    client = TestClient(main.app)
    runs: dict[str, dict] = {}
    for v in SC["vehicles"]:
        inc = client.post("/incidents", json={"type": "fire" if v["type"] == "fire" else "medical"}).json()[
            "incident_id"
        ]
        start = {
            "action": "start",
            "plate": v["plate"],
            "incident_id": inc,
            "corridor": "blr",
            "destination": BLR["hospital"],
        }
        rid = client.post("/runs", json={**start, "source": "sim", "scenario": NAME}).json()["run_id"]
        fake.collection("runs").document(rid).collection("log").document("0").set(
            {
                "t": datetime.now(UTC),
                "kind": "form",
                "transcript_en": "replay entry",
                "fields": {"complaint": "chest pain"},
            }
        )
        client.post(f"/runs/{rid}/confirm", json={"tier": v["tier"]})
        runs[v["tier"]] = {
            "id": rid,
            "type": v["type"],
            "plate": v["plate"],
            "ticks": [],
            "next": [],
            "brief_at": None,
        }

    events = sorted(
        ((v["start_offset_s"] + k["t"], v["tier"], k) for v in SC["vehicles"] for k in v["ticks"]),
        key=lambda e: e[:2],
    )
    base = datetime.now(UTC).replace(microsecond=0)
    for sim, tier, k in events:
        run = runs[tier]
        body = {
            "run_id": run["id"],
            "lat": k["lat"],
            "lng": k["lng"],
            "speed_mps": k["speed_mps"],
            "source": "sim",
        }
        r = client.post("/location", json={**body, "t": (base + timedelta(seconds=sim)).isoformat()})
        if r.status_code != 200:  # an arrived run refuses later ticks
            run.setdefault("refused", []).append(r.json()["error"])
            continue
        out = r.json()
        run["ticks"].append({"sim": sim, **out})
        if out["next_junction"] and (not run["next"] or run["next"][-1] != out["next_junction"]):
            run["next"].append(out["next_junction"])
        doc = fake.collection("runs").document(run["id"]).get().to_dict()
        if run["type"] == "ambulance" and doc.get("brief_fired") and run["brief_at"] is None:
            run["brief_at"] = {
                "tick": len(run["ticks"]),
                "passed": doc["passed_junctions"],
                "distance_m": doc["distance_m"],
            }

    for run in runs.values():
        run["report_at_arrival"] = (
            fake.collection("reports").document(run["id"]).get().exists
        )  # before any POST /runs end
        run["end"] = client.post("/runs", json={"action": "end", "run_id": run["id"]}).json()
        ref = fake.collection("runs").document(run["id"])
        run["alerts"] = collect(ref.collection("alerts"))
        run["doc"] = ref.get().to_dict()
        run["brief"] = fake.collection("briefs").document(run["id"]).get().to_dict()
    runs["audit"] = {
        "events": collect(fake.collection("audit")),
        "junctions": {d.id: d.to_dict() for d in fake.collection("junctions").stream()},
    }
    yield runs
    fake.clear()


def by_run(replay: dict) -> dict[str, dict]:
    return {r["id"]: r for t, r in replay.items() if t != "audit"}


def alerts_of(replay: dict, stage: str | None = None) -> list[dict]:
    return [a for r in by_run(replay).values() for a in r["alerts"] if stage in (None, a["stage"])]


def test_replay_drove_every_vehicle(replay: dict) -> None:
    for tier in ("critical", "urgent", "fire_with_trapped"):
        assert replay[tier]["ticks"], tier
    assert all(r["ticks"][0]["state"] == "en_route" for t, r in replay.items() if t != "audit")


def test_prepare_only_for_queues_of_50m_or_more(replay: dict) -> None:
    prepare = alerts_of(replay, "PREPARE")
    assert prepare and all(a["jam_m"] >= main.PREPARE_MIN_JAM_M for a in prepare)
    assert any(
        a["jam_m"] < main.PREPARE_MIN_JAM_M for a in alerts_of(replay, "STOP")
    )  # STOP fires whatever the queue


def test_alerts_are_text_only_offline(replay: dict) -> None:
    assert alerts_of(replay) and all(
        a["audio_url"] is None and a["text_local"] == a["text"] for a in alerts_of(replay)
    )


def test_one_stop_per_junction_per_run(replay: dict) -> None:
    for r in by_run(replay).values():
        stops = Counter(a["junction_id"] for a in r["alerts"] if a["stage"] == "STOP")
        assert stops and max(stops.values()) == 1, stops
        assert (
            Counter(a["junction_id"] for a in r["alerts"] if a["stage"] == "PREPARE").most_common(1)[0][1]
            == 1
        )


def test_next_junction_only_moves_forward(replay: dict) -> None:
    for tier, r in replay.items():
        if tier != "audit":
            idx = [ORDER.index(j) for j in r["next"]]
            assert idx == sorted(set(idx)), r["next"]
    assert replay["critical"]["next"][0] == "blr_j1"


def test_junctions_passed_are_a_prefix(replay: dict) -> None:
    passed = replay["critical"]["doc"]["passed_junctions"]
    assert passed == ORDER[: len(passed)] and len(passed) >= 4


def junction_sequences(replay: dict, jid: str) -> list[dict[str, int]]:
    tier = {r["id"]: t for t, r in replay.items() if t != "audit"}
    return [
        {tier[s["run_id"]]: s["offset_s"] for s in e["sequence"]}
        for e in replay["audit"]["events"]
        if e["action"] == "preempt_requested" and e["junction_id"] == jid
    ]


def test_j3_fire_goes_first_and_the_ambulances_share_a_slot(replay: dict) -> None:
    seqs = junction_sequences(replay, "blr_j3")
    both = [s for s in seqs if {"critical", "urgent"} <= set(s)]
    assert both and all(s["critical"] == s["urgent"] for s in both)
    with_fire = [s for s in both if "fire_with_trapped" in s]
    assert with_fire, seqs
    assert all(
        s["fire_with_trapped"] == 0 and s["critical"] == 12 for s in with_fire
    )  # fire first, ambulances one gap later


def test_phase_is_written_to_the_junction(replay: dict) -> None:
    j3 = replay["audit"]["junctions"]["blr_j3"]
    assert j3["phase"]["approach"] and j3["phase"]["sequence"] and j3["lang"] == "kn"


def test_brief_waits_until_the_run_is_under_way(replay: dict) -> None:
    at = replay["critical"]["brief_at"]
    assert at and at["tick"] > 1 and (at["passed"] or at["distance_m"] >= main.BRIEF_MIN_M)
    assert replay["critical"]["brief"]["model"] == "offline"
    assert all(not (r["brief_at"] and r["brief_at"]["tick"] == 1) for r in by_run(replay).values())
    assert (
        replay["critical"]["doc"]["brief_fired"] is True and replay["critical"]["doc"]["brief_due"] is False
    )


def test_fire_has_no_brief_and_no_routing(replay: dict) -> None:
    fire = replay["fire_with_trapped"]
    assert fire["brief"] is None and not fire["doc"].get("brief_fired") and "routing" not in fire["doc"]


def test_scenario_routing_is_recorded_not_applied(replay: dict) -> None:
    for tier in ("critical", "urgent"):
        routing = replay[tier]["doc"]["routing"]
        assert routing["applied"] is False and routing["reason"] == "scenario run keeps corridor hospital"
        assert replay[tier]["doc"]["destination"]["name"] == BLR["hospital"]["name"]


def test_ambulances_arrive_and_the_report_counts_from_the_first_tick(replay: dict) -> None:
    for tier in ("critical", "urgent"):
        r = replay[tier]
        assert (
            r["ticks"][-1]["state"] == "arrived" and r["doc"]["state"] == "ended"
        )  # then ended by the POST /runs end
        assert set(r.get("refused", ["run_not_active"])) == {"run_not_active"}
        assert r["report_at_arrival"] is True  # written by the arriving tick, not by the end call
        report = r["end"]["report"]
        assert report["actual_s"] == r["ticks"][-1]["sim"] - r["ticks"][0]["sim"]
        assert report["run_id"] == r["id"] and report["junctions_cleared"] >= 1
