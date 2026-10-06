"""POST /location with an Idempotency-Key header or tick_id: a repeat within 10 minutes returns the first response and
writes nothing."""

import copy
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from httpx import Response

from fakefs import FakeFirestore
from test_api import BLR_HOSPITAL, assert_envelope, run_doc, start
from test_location import START, T0


def run(client: TestClient) -> str:
    return start(client, scenario="blr-two-vehicles", source="sim", destination=BLR_HOSPITAL)


def tick(client: TestClient, rid: str, seq: int = 0, key: str | None = None, **body: object) -> Response:
    headers = {"Idempotency-Key": key} if key else {}
    payload = {
        "run_id": rid,
        "lat": START[0],
        "lng": START[1],
        "speed_mps": 10.0,
        "t": (T0 + timedelta(seconds=5 * seq)).isoformat(),
        **body,
    }
    return client.post("/location", json=payload, headers=headers)


def stored(db: FakeFirestore, rid: str) -> dict[str, dict]:
    pre = f"idempotency/{rid}/keys/"
    return {k.removeprefix(pre): v for k, v in db.docs.items() if k.startswith(pre)}


def test_the_first_call_is_processed_and_its_response_is_stored(
    client: TestClient, seeded: FakeFirestore
) -> None:
    rid = run(client)
    r = tick(client, rid, key="k-1")
    assert r.status_code == 200 and "Idempotent-Replayed" not in r.headers
    doc = stored(seeded, rid)["k-1"]
    assert doc["response"] == r.json()
    assert (
        abs((doc["expires_at"] - datetime.now(UTC)).total_seconds() - 600) < 5
    )  # the window; a TTL policy deletes by it


def test_a_repeat_returns_the_stored_response_and_writes_nothing(
    client: TestClient, seeded: FakeFirestore
) -> None:
    rid = run(client)
    first = tick(client, rid, key="k-1")
    before = copy.deepcopy(seeded.docs)
    again = tick(client, rid, seq=1, key="k-1", lat=START[0] + 0.01)  # even a different body: the key decides
    assert again.status_code == 200 and again.headers["Idempotent-Replayed"] == "true"
    assert again.json() == first.json()
    assert seeded.docs == before  # no tick, no alert, no run update, no new document
    assert len(run_doc(seeded, rid)["ticks"]) == 1


def test_tick_id_in_the_body_works_like_the_header(client: TestClient, seeded: FakeFirestore) -> None:
    rid = run(client)
    first = tick(client, rid, tick_id="t-1")
    again = tick(client, rid, seq=1, tick_id="t-1")
    assert again.headers["Idempotent-Replayed"] == "true" and again.json() == first.json()
    assert list(stored(seeded, rid)) == ["t-1"] and len(run_doc(seeded, rid)["ticks"]) == 1


def test_the_header_wins_over_tick_id(client: TestClient, seeded: FakeFirestore) -> None:
    rid = run(client)
    tick(client, rid, key="from-header", tick_id="from-body")
    assert list(stored(seeded, rid)) == ["from-header"]


def test_a_new_key_is_a_new_tick(client: TestClient, seeded: FakeFirestore) -> None:
    rid = run(client)
    tick(client, rid, seq=0, key="a")
    r = tick(client, rid, seq=1, key="b")
    assert "Idempotent-Replayed" not in r.headers and len(run_doc(seeded, rid)["ticks"]) == 2
    assert set(stored(seeded, rid)) == {"a", "b"}


def test_keys_belong_to_a_run(client: TestClient, seeded: FakeFirestore) -> None:
    one, two = run(client), run(client)  # the second supersedes the first run, which is fine for this
    tick(client, two, key="same")
    other = tick(client, two, seq=1, key="same")
    assert other.headers["Idempotent-Replayed"] == "true"
    assert stored(seeded, one) == {}


def test_no_key_means_no_stored_response(client: TestClient, seeded: FakeFirestore) -> None:
    rid = run(client)
    tick(client, rid, seq=0)
    tick(client, rid, seq=1)
    assert not any(k.startswith("idempotency/") for k in seeded.docs)
    assert len(run_doc(seeded, rid)["ticks"]) == 2


def test_after_ten_minutes_the_key_is_free_again(client: TestClient, seeded: FakeFirestore) -> None:
    rid = run(client)
    tick(client, rid, key="k-1")
    seeded.docs[f"idempotency/{rid}/keys/k-1"]["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    r = tick(client, rid, seq=1, key="k-1")
    assert "Idempotent-Replayed" not in r.headers and len(run_doc(seeded, rid)["ticks"]) == 2
    assert stored(seeded, rid)["k-1"]["expires_at"] > datetime.now(UTC)  # stored afresh


def test_a_retry_after_the_run_ended_still_gets_the_first_answer(
    client: TestClient, seeded: FakeFirestore
) -> None:
    rid = run(client)
    first = tick(client, rid, key="k-1")
    client.post("/runs", json={"action": "end", "run_id": rid})
    assert tick(client, rid, seq=1, key="k-1").json() == first.json()
    assert_envelope(
        tick(client, rid, seq=1, key="k-2"), 403, "run_not_active"
    )  # a new tick is refused as before
    assert "k-2" not in stored(seeded, rid)  # refusals are not stored


def test_a_malformed_key_is_a_validation_error(client: TestClient, seeded: FakeFirestore) -> None:
    rid = run(client)
    assert_envelope(tick(client, rid, key="a/b"), 422, "validation_error")
    assert_envelope(tick(client, rid, key="x" * 129), 422, "validation_error")
    assert_envelope(tick(client, rid, tick_id="a b"), 422, "validation_error")
    assert not any(k.startswith("idempotency/") for k in seeded.docs)
