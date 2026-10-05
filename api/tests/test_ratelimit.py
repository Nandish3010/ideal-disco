"""Per-IP rate limits, the per-run caps (triage + log calls, briefs) and the atomic log counter."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

import main
import ratelimit
from fakefs import FakeFirestore
from test_api import assert_envelope, run_doc, start


@pytest.fixture
def limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RATE_LIMIT_DISABLED")


def ip(n: int) -> dict[str, str]:
    return {"X-Forwarded-For": f"10.0.0.{n}"}


# ---- token buckets ---------------------------------------------------------------------------------------------------


def test_heavy_endpoints_allow_10_a_minute_then_429(client: TestClient, limits: None) -> None:
    for _ in range(10):
        assert client.post("/brief", json={"run_id": "run-nope"}, headers=ip(1)).status_code == 404
    r = client.post("/brief", json={"run_id": "run-nope"}, headers=ip(1))
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1 and r.headers["X-Request-Id"]
    assert client.post("/brief", json={"run_id": "run-nope"}, headers=ip(2)).status_code == 404  # per IP
    assert client.get("/health", headers=ip(1)).status_code == 200  # health is never limited


def test_every_heavy_path_shares_the_budget(client: TestClient, limits: None) -> None:
    for path in ("/triage", "/log", "/brief", "/route", "/runs/run-x/after-action"):
        assert ratelimit.kind(path) == "heavy", path
    assert ratelimit.kind("/location") == "location" and ratelimit.kind("/ack") == "general"
    for _ in range(5):
        client.post("/triage", json={"run_id": "run-nope", "text": "x"}, headers=ip(3))
        client.post("/runs/run-nope/after-action", headers=ip(3))
    assert client.post("/route", json={"run_id": "run-nope"}, headers=ip(3)).status_code == 429


def test_other_endpoints_allow_60_a_minute(client: TestClient, limits: None) -> None:
    assert [client.get("/nope", headers=ip(4)).status_code for _ in range(60)] == [404] * 60
    assert_envelope(client.get("/nope", headers=ip(4)), 429, "rate_limited")
    assert client.post("/brief", json={"run_id": "x"}, headers=ip(4)).status_code == 404  # its own bucket


def test_tokens_come_back_with_time(
    client: TestClient, limits: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: clock[0])
    for _ in range(10):
        client.post("/brief", json={"run_id": "run-nope"}, headers=ip(5))
    assert client.post("/brief", json={"run_id": "run-nope"}, headers=ip(5)).status_code == 429
    clock[0] += 6  # 10 a minute: one token per 6 s
    assert client.post("/brief", json={"run_id": "run-nope"}, headers=ip(5)).status_code == 404
    assert client.post("/brief", json={"run_id": "run-nope"}, headers=ip(5)).status_code == 429


def test_a_forged_forwarded_for_prefix_does_not_buy_a_new_budget(client: TestClient, limits: None) -> None:
    for n in range(10):
        client.post("/brief", json={"run_id": "x"}, headers={"X-Forwarded-For": f"6.6.6.{n}, 9.9.9.9"})
    r = client.post("/brief", json={"run_id": "x"}, headers={"X-Forwarded-For": "1.2.3.4, 9.9.9.9"})
    assert r.status_code == 429


def test_the_bucket_table_is_bounded(limits: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 3)
    for n in range(10):
        ratelimit.retry_after(f"ip-{n}", "/nope")
    assert len(ratelimit._buckets) <= 4


def test_disabled_never_limits(client: TestClient) -> None:  # conftest sets RATE_LIMIT_DISABLED=1
    assert all(client.post("/brief", json={"run_id": "x"}).status_code == 404 for _ in range(30))


# ---- per-run caps ----------------------------------------------------------------------------------------------------


def test_triage_and_log_are_capped_at_20_per_run(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client)
    for k in range(main.MAX_EXTRACTS):
        path = "/triage" if k % 2 else "/log"  # one shared count
        assert client.post(path, json={"run_id": rid, "text": "chest pain"}).status_code == 422
    assert run_doc(seeded, rid)["extract_calls"] == main.MAX_EXTRACTS
    for path in ("/triage", "/log"):
        assert_envelope(client.post(path, json={"run_id": rid, "text": "x"}), 429, "run_cap_reached")
    other = start(client, plate="KA01AB4321")  # another run has its own budget
    assert client.post("/triage", json={"run_id": other, "text": "x"}).status_code == 422
    assert run_doc(seeded, rid)["extract_calls"] == main.MAX_EXTRACTS  # refused calls are not counted


def test_a_rejected_request_does_not_use_up_the_cap(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client)
    client.post("/triage", json={"run_id": rid})  # 400: nothing to extract from
    assert "extract_calls" not in run_doc(seeded, rid)


def write_brief_entry(db: FakeFirestore, rid: str) -> None:
    db.collection("runs").document(rid).collection("log").document("1").set(
        {"t": datetime.now(UTC), "fields": {}}
    )


def test_one_brief_per_ten_minutes_unless_regenerate(client: TestClient, seeded: FakeFirestore) -> None:
    rid = start(client)
    write_brief_entry(seeded, rid)
    assert client.post("/brief", json={"run_id": rid}).status_code == 200
    body = assert_envelope(client.post("/brief", json={"run_id": rid}), 429, "brief_cooldown")
    assert 590 <= body["retry_after_s"] <= 600
    assert client.post("/brief", json={"run_id": rid, "regenerate": True}).status_code == 200
    seeded.collection("briefs").document(rid).update(
        {"generated_at": datetime.now(UTC) - timedelta(minutes=11)}
    )
    assert client.post("/brief", json={"run_id": rid}).status_code == 200  # the window has passed


# ---- atomic log counter ----------------------------------------------------------------------------------------------


@pytest.fixture
def extracting(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_extract(*a: Any, **kw: Any) -> dict:
        return {"transcript_en": "oxygen started", "interventions": [{"kind": "drug", "name": "oxygen"}]}

    monkeypatch.setattr(main, "extract", fake_extract)


def test_log_entries_are_numbered_by_the_counter(
    client: TestClient, seeded: FakeFirestore, extracting: None
) -> None:
    rid = start(client)
    first = client.post("/log", json={"run_id": rid, "text": "x"}).json()
    second = client.post("/log", json={"run_id": rid, "text": "y"}).json()
    assert (first["n"], second["n"]) == (1, 2)
    assert run_doc(seeded, rid)["log_count"] == 2
    ids = sorted(d.id for d in seeded.collection("runs").document(rid).collection("log").stream())
    assert ids == ["1", "2"]
    assert [e["transcript_en"] for e in main.log_entries(seeded.collection("runs").document(rid))] == [
        "oxygen started"
    ] * 2


def test_the_counter_never_reuses_a_number_the_log_already_has(
    client: TestClient, seeded: FakeFirestore, extracting: None
) -> None:
    """A run with entries but no counter yet (written before the counter existed) starts after them."""
    rid = start(client)
    log = seeded.collection("runs").document(rid).collection("log")
    log.document("0").set({"t": datetime.now(UTC), "transcript_en": "old 0"})
    log.document("1").set({"t": datetime.now(UTC), "transcript_en": "old 1"})
    assert client.post("/log", json={"run_id": rid, "text": "x"}).json()["n"] == 3
    assert client.post("/log", json={"run_id": rid, "text": "x"}).json()["n"] == 4
    assert log.document("0").get().to_dict()["transcript_en"] == "old 0"
    assert log.document("1").get().to_dict()["transcript_en"] == "old 1"


def test_triage_shares_the_numbering(client: TestClient, seeded: FakeFirestore, extracting: None) -> None:
    rid = start(client)
    client.post("/triage", json={"run_id": rid, "text": "x"})
    assert client.post("/log", json={"run_id": rid, "text": "x"}).json()["n"] == 2
