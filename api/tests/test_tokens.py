"""Device-scoped tokens: bind and go-on-duty hand out a token, the protected calls check its sha256 (401 missing, 403 wrong)."""

import hashlib
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from httpx import Response

import tokens
from fakefs import FakeFirestore
from test_api import AMB, BLR_HOSPITAL, FIRE, alerting_run, assert_envelope, new_incident

Headers = dict[str, str]


@pytest.fixture
def enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """conftest turns tokens off for the older tests; the default (env unset) is enforced."""
    monkeypatch.delenv("DEVICE_TOKENS_DISABLED")


def bind(client: TestClient, plate: str = AMB, device: str = "d1") -> str:
    r = client.post("/vehicles/bind", json={"plate": plate, "device_id": device})
    assert r.status_code == 200, r.text
    return r.json()["device_token"]


def hdr(token: str | None) -> Headers:
    return {"X-Device-Token": token} if token else {}


def on_duty(client: TestClient, junction: str = "j3", device: str = "cop-1") -> str:
    r = client.post(
        "/duty", json={"corridor": "blr", "junction_id": junction, "device_id": device, "on": True}
    )
    assert r.status_code == 200, r.text
    return r.json()["device_token"]


def start(client: TestClient, token: str, plate: str = AMB) -> str:
    body = {
        "action": "start",
        "plate": plate,
        "incident_id": new_incident(client),
        "corridor": "blr",
        "scenario": "blr-two-vehicles",
        "source": "sim",
        "destination": BLR_HOSPITAL,
    }
    r = client.post("/runs", json=body, headers=hdr(token))
    assert r.status_code == 200, r.text
    return r.json()["run_id"]


# ---- bind -------------------------------------------------------------------------------------------------------------


def test_bind_returns_a_token_and_stores_only_its_hash(client: TestClient, seeded: FakeFirestore) -> None:
    r = client.post("/vehicles/bind", json={"plate": AMB, "device_id": "d1"}).json()
    token = r["device_token"]
    assert len(token) >= 43 and "device_token_hash" not in r
    v = seeded.collection("vehicles").document(AMB).get().to_dict()
    assert (
        v["device_token_hash"] == hashlib.sha256(token.encode()).hexdigest() and v["bound_device_id"] == "d1"
    )
    assert token not in str(v)


def test_rebind_rotates_the_token(client: TestClient, seeded: FakeFirestore, enforced: None) -> None:
    first = bind(client, device="phone")
    rid = start(client, first)
    second = bind(client, device="sim-KA01AB1234")
    assert second != first
    stale = client.post(f"/runs/{rid}/confirm", json={"tier": "critical"}, headers=hdr(first))
    assert_envelope(stale, 403, "device_token_mismatch")
    assert (
        client.post(f"/runs/{rid}/confirm", json={"tier": "critical"}, headers=hdr(second)).status_code == 200
    )


# ---- the protected calls ----------------------------------------------------------------------------------------------

LOC = {"lat": 12.9145, "lng": 77.6361, "speed_mps": 5, "source": "sim"}
CALLS: dict[str, Callable[[TestClient, str, Headers], Response]] = {
    "runs_end": lambda c, rid, h: c.post("/runs", json={"action": "end", "run_id": rid}, headers=h),
    "triage": lambda c, rid, h: c.post("/triage", json={"run_id": rid, "text": "chest pain"}, headers=h),
    "log": lambda c, rid, h: c.post("/log", json={"run_id": rid, "text": "aspirin"}, headers=h),
    "location": lambda c, rid, h: c.post("/location", json={"run_id": rid, **LOC}, headers=h),
    "confirm": lambda c, rid, h: c.post(f"/runs/{rid}/confirm", json={"tier": "critical"}, headers=h),
}


@pytest.mark.parametrize("name", CALLS)
def test_run_calls_need_the_run_vehicles_token(
    client: TestClient, seeded: FakeFirestore, enforced: None, name: str
) -> None:
    mine, other = bind(client, AMB), bind(client, FIRE)
    rid = start(client, mine)
    call = CALLS[name]
    assert_envelope(call(client, rid, {}), 401, "device_token_required")
    assert_envelope(call(client, rid, hdr("not-a-token")), 403, "device_token_mismatch")
    assert_envelope(call(client, rid, hdr(other)), 403, "device_token_mismatch")  # another vehicle's token
    ok = call(client, rid, hdr(mine))
    assert ok.status_code in (200, 422), (
        ok.text
    )  # /triage and /log are 422 extraction_failed offline: past the check
    if ok.status_code == 422:
        assert ok.json()["error"] == "extraction_failed"


def test_unknown_run_is_404_before_the_token_check(
    client: TestClient, seeded: FakeFirestore, enforced: None
) -> None:
    assert_envelope(CALLS["location"](client, "run-nope", {}), 404, "unknown_run")
    assert_envelope(CALLS["runs_end"](client, "run-nope", {}), 404, "unknown_run")


def test_start_needs_the_vehicles_token(client: TestClient, seeded: FakeFirestore, enforced: None) -> None:
    body = {"action": "start", "plate": AMB, "incident_id": new_incident(client), "corridor": "blr"}
    assert_envelope(client.post("/runs", json=body), 401, "device_token_required")
    # a registered vehicle nobody has bound has no token to match
    assert_envelope(client.post("/runs", json=body, headers=hdr("guess")), 403, "device_token_mismatch")
    mine, other = bind(client, AMB), bind(client, FIRE)
    assert_envelope(client.post("/runs", json=body, headers=hdr(other)), 403, "device_token_mismatch")
    assert client.post("/runs", json=body, headers=hdr(mine)).status_code == 200


# ---- duty and ack -----------------------------------------------------------------------------------------------------


def test_duty_on_returns_a_token_and_off_needs_it(
    client: TestClient, seeded: FakeFirestore, enforced: None
) -> None:
    token = on_duty(client)
    doc = seeded.collection("duty").document("blr_j3").get().to_dict()
    assert doc["device_token_hash"] == hashlib.sha256(token.encode()).hexdigest() and doc["on"] is True
    off = {"corridor": "blr", "junction_id": "j3", "device_id": "cop-1", "on": False}
    assert_envelope(client.post("/duty", json=off), 401, "device_token_required")
    assert_envelope(client.post("/duty", json=off, headers=hdr("nope")), 403, "device_token_mismatch")
    other_junction = on_duty(client, "j4")
    assert_envelope(client.post("/duty", json=off, headers=hdr(other_junction)), 403, "device_token_mismatch")
    r = client.post("/duty", json=off, headers=hdr(token))
    assert r.status_code == 200 and "device_token" not in r.json()
    doc = seeded.collection("duty").document("blr_j3").get().to_dict()
    assert doc["on"] is False and "device_token_hash" not in doc  # the token dies with the shift


def test_a_second_cop_going_on_duty_rotates_the_junctions_token(
    client: TestClient, seeded: FakeFirestore, enforced: None
) -> None:
    first, second = on_duty(client, device="cop-1"), on_duty(client, device="cop-2")
    assert first != second
    off = {"corridor": "blr", "junction_id": "j3", "device_id": "cop-1", "on": False}
    assert client.post("/duty", json=off, headers=hdr(first)).status_code == 403
    assert client.post("/duty", json=off, headers=hdr(second)).status_code == 200


def test_ack_takes_the_on_duty_cops_token_or_the_runs_vehicle_token(
    client: TestClient, seeded: FakeFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid, n = alerting_run(client, seeded)  # run set up with tokens off
    alert = seeded.collection("runs").document(rid).collection("alerts").document(str(n))
    jid = alert.get().to_dict()["junction_id"]
    monkeypatch.delenv("DEVICE_TOKENS_DISABLED")
    body = {"run_id": rid, "alert_n": n, "junction_id": jid, "device_id": "cop-1"}
    cop = client.post(
        "/duty", json={"corridor": "blr", "junction_id": jid, "device_id": "cop-1", "on": True}
    ).json()["device_token"]
    vehicle, other_cop = bind(client, AMB), on_duty(client, "j5")
    assert_envelope(client.post("/ack", json=body), 401, "device_token_required")
    assert_envelope(client.post("/ack", json=body, headers=hdr("nope")), 403, "device_token_mismatch")
    assert_envelope(client.post("/ack", json=body, headers=hdr(other_cop)), 403, "device_token_mismatch")
    assert_envelope(
        client.post("/ack", json=body, headers=hdr(bind(client, FIRE))), 403, "device_token_mismatch"
    )
    assert alert.get().to_dict()["acked_at"] is None
    assert client.post("/ack", json=body, headers=hdr(cop)).json()["ok"] is True
    assert alert.get().to_dict()["acked_at"] is not None
    alert.update({"acked_at": None})
    assert (
        client.post("/ack", json=body, headers=hdr(vehicle)).json()["ok"] is True
    )  # the vehicle may ack too
    off = {"corridor": "blr", "junction_id": jid, "device_id": "cop-1", "on": False}
    assert client.post("/duty", json=off, headers=hdr(cop)).status_code == 200
    assert_envelope(
        client.post("/ack", json=body, headers=hdr(cop)), 403, "device_token_mismatch"
    )  # off duty


def test_unknown_alert_is_404_before_the_token_check(
    client: TestClient, seeded: FakeFirestore, enforced: None
) -> None:
    body = {"run_id": "run-x", "alert_n": 0, "junction_id": "blr_j3"}
    assert_envelope(client.post("/ack", json=body), 404, "unknown_alert")


# ---- paid endpoints: /route, regenerate -------------------------------------------------------------------------------


def desk(client: TestClient, hospital: str = "blr_jayadeva") -> str:
    r = client.post("/hospital/duty", json={"hospital_id": hospital})
    assert r.status_code == 200, r.text
    return r.json()["hospital_token"]


def test_hospital_duty_stores_only_the_hash_and_rotates(
    client: TestClient, seeded: FakeFirestore, enforced: None
) -> None:
    first = desk(client)
    h = seeded.collection("hospital_duty").document("blr_jayadeva").get().to_dict()["device_token_hash"]
    assert h == hashlib.sha256(first.encode()).hexdigest() and first not in str(h)
    assert desk(client) != first
    assert_envelope(client.post("/hospital/duty", json={"hospital_id": "nope"}), 404, "unknown_hospital")


def test_route_needs_the_vehicle_token(client: TestClient, seeded: FakeFirestore, enforced: None) -> None:
    t = bind(client)
    rid = start(client, t)
    client.post(f"/runs/{rid}/confirm", json={"tier": "urgent"}, headers=hdr(t))
    assert_envelope(client.post("/route", json={"run_id": rid}), 401, "device_token_required")
    assert_envelope(
        client.post("/route", json={"run_id": rid}, headers=hdr("x")), 403, "device_token_mismatch"
    )
    assert_envelope(
        client.post("/route", json={"run_id": rid}, headers=hdr(desk(client))), 403, "device_token_mismatch"
    )  # a hospital desk cannot spend the routing agent
    assert client.post("/route", json={"run_id": rid}, headers=hdr(t)).status_code == 200


def test_brief_regenerate_needs_vehicle_or_hospital_token(
    client: TestClient, seeded: FakeFirestore, enforced: None
) -> None:
    t = bind(client)
    rid = start(client, t)
    seeded.collection("runs").document(rid).collection("log").document("1").set({"t": 0, "fields": {}})
    body = {"run_id": rid}
    assert client.post("/brief", json=body).status_code == 200  # first generation stays open
    assert_envelope(client.post("/brief", json={**body, "regenerate": True}), 401, "device_token_required")
    bad = client.post("/brief", json={**body, "regenerate": True}, headers=hdr("x"))
    assert_envelope(bad, 403, "device_token_mismatch")
    for good in (t, desk(client)):
        r = client.post("/brief", json={**body, "regenerate": True}, headers=hdr(good))
        assert r.status_code == 200, r.text


def test_after_action_regenerate_needs_vehicle_or_hospital_token(
    client: TestClient, seeded: FakeFirestore, enforced: None
) -> None:
    t = bind(client)
    rid = start(client, t)
    seeded.collection("runs").document(rid).update({"state": "ended"})
    url = f"/runs/{rid}/after-action"
    assert client.post(url).status_code == 200  # first report stays open
    assert client.post(url).status_code == 200
    assert_envelope(client.post(url + "?regenerate=1"), 401, "device_token_required")
    assert_envelope(client.post(url + "?regenerate=1", headers=hdr("x")), 403, "device_token_mismatch")
    for good in (t, desk(client)):
        assert client.post(url + "?regenerate=1", headers=hdr(good)).status_code == 200


# ---- what stays open --------------------------------------------------------------------------------------------------


def test_open_endpoints_need_no_token(client: TestClient, seeded: FakeFirestore, enforced: None) -> None:
    assert client.get("/health").status_code == 200
    assert client.post("/incidents", json={"type": "cardiac"}).status_code == 200
    assert_envelope(client.post("/route", json={"run_id": "run-x"}), 404, "unknown_run")
    assert_envelope(client.post("/brief", json={"run_id": "run-x", "regenerate": True}), 404, "unknown_run")
    assert_envelope(client.post("/runs/run-x/after-action?regenerate=1"), 404, "unknown_run")
    assert client.post("/housekeeping").status_code == 404  # its own token, unset here


def test_tokens_can_be_switched_off(client: TestClient, seeded: FakeFirestore) -> None:
    body = {"action": "start", "plate": AMB, "incident_id": new_incident(client), "corridor": "blr"}
    assert client.post("/runs", json=body).status_code == 200  # DEVICE_TOKENS_DISABLED=1 from conftest


def test_problem_codes(enforced: None) -> None:
    h = tokens.digest("a")
    assert tokens.problem("", [h]) == (401, "device_token_required")
    assert tokens.problem("b", [h, None]) == (403, "device_token_mismatch")
    assert tokens.problem("a", [None, h]) is None
