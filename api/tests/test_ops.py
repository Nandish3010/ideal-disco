"""Operations: tracing (a no-op unless OTEL_ENABLED=1), FCM push to the cop on duty, production mode and its token-gated reads."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from firebase_admin import messaging

import main
import push
import telemetry
from fakefs import FakeFirestore
from logctx import log
from test_api import AMB, assert_envelope

# ---- tracing ---------------------------------------------------------------------------------------------------------


def test_tracing_is_a_noop_when_disabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    assert telemetry.enabled() is False and telemetry.setup(FastAPI()) is False
    assert telemetry.trace_id() is None
    with telemetry.span("x", a=1) as s:
        assert s is None
    assert telemetry.traced("x")(lambda a, b=2: a + b)(1) == 3
    log(event="e")
    assert "trace_id" not in json.loads(capsys.readouterr().out)


@pytest.fixture
def tracer(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A real SDK tracer exporting to memory, in place of the Cloud Trace one."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    mem = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(mem))
    monkeypatch.setattr(telemetry, "_tracer", provider.get_tracer("t"))
    return mem


def test_spans_and_trace_id_in_log_lines(tracer: Any, capsys: pytest.CaptureFixture[str]) -> None:
    @telemetry.traced("leadtime")
    def work() -> None:
        log(event="inside")

    log(event="outside")
    work()
    outside, inside = (json.loads(x) for x in capsys.readouterr().out.splitlines())
    assert "trace_id" not in outside
    span = tracer.get_finished_spans()[0]
    assert span.name == "leadtime" and inside["trace_id"] == f"{span.context.trace_id:032x}"
    assert inside["logging.googleapis.com/trace"].endswith("/traces/" + inside["trace_id"])


def test_setup_failure_leaves_the_service_untraced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_ENABLED", "1")
    monkeypatch.setenv("OTEL_SAMPLE_RATIO", "not a number")
    assert telemetry.setup(FastAPI()) is False and telemetry._tracer is None


# ---- FCM push --------------------------------------------------------------------------------------------------------

ALERT = {"junction_id": "blr_j3", "stage": "PREPARE", "text": "AMBULANCE CRITICAL", "text_local": None}


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """firebase-admin with only `send` replaced: the message objects are the real ones, so a bad payload still fails."""
    out: list[Any] = []
    monkeypatch.setattr(push, "_messaging", lambda: messaging)
    monkeypatch.setattr(messaging, "send", out.append)
    return out


def alert_ref(db: FakeFirestore, duty: dict | None) -> Any:
    if duty is not None:
        db.collection("duty").document("blr_j3").set(duty)
    ref = db.collection("runs").document("run-1").collection("alerts").document("0")
    ref.set(ALERT)
    return ref


def test_push_sends_text_and_audio_to_the_cop_on_duty(db: FakeFirestore, sent: list[Any]) -> None:
    ref = alert_ref(db, {"on": True, "fcm_token": "tok-1"})
    assert push.send_alert(ref, "gs://m/a.mp3") is True
    (m,) = sent
    assert m.token == "tok-1" and m.notification.body == "AMBULANCE CRITICAL"
    assert m.data == {
        "run_id": "run-1",
        "alert_n": "0",
        "junction_id": "blr_j3",
        "stage": "PREPARE",
        "text": "AMBULANCE CRITICAL",
        "audio_url": "gs://m/a.mp3",
    }
    assert m.webpush.headers["Urgency"] == "high"


@pytest.mark.parametrize("duty", [None, {"on": True}, {"on": False, "fcm_token": "tok"}])
def test_push_needs_an_on_duty_cop_with_a_token(
    db: FakeFirestore, sent: list[Any], duty: dict | None
) -> None:
    assert push.send_alert(alert_ref(db, duty), None) is False and sent == []


def test_push_failure_is_logged_not_raised(
    db: FakeFirestore, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(_: Any) -> None:
        raise RuntimeError("fcm down")

    monkeypatch.setattr(push, "_messaging", lambda: messaging)
    monkeypatch.setattr(messaging, "send", boom)
    assert push.send_alert(alert_ref(db, {"on": True, "fcm_token": "tok"}), None) is False
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["event"] == "push_error"


def test_a_dropped_subscription_clears_the_token(db: FakeFirestore, monkeypatch: pytest.MonkeyPatch) -> None:
    def gone(_: Any) -> None:
        raise messaging.UnregisteredError("unregistered", None, None)

    monkeypatch.setattr(push, "_messaging", lambda: messaging)
    monkeypatch.setattr(messaging, "send", gone)
    push.send_alert(alert_ref(db, {"on": True, "fcm_token": "tok"}), None)
    assert "fcm_token" not in db.collection("duty").document("blr_j3").get().to_dict()


def test_finish_alert_pushes_with_the_audio_url(
    db: FakeFirestore, sent: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = alert_ref(db, {"on": True, "fcm_token": "tok"})
    monkeypatch.setattr(main, "speak", lambda text, lang, path: ("gs://m/x.mp3", "ಸ್ಥಳೀಯ"))
    main.finish_alert(ref, "AMBULANCE CRITICAL", "kn", "p.mp3")
    assert sent[0].data["audio_url"] == "gs://m/x.mp3" and sent[0].notification.body == "ಸ್ಥಳೀಯ"


def duty_body(**kw: Any) -> dict:
    return {"corridor": "blr", "junction_id": "j3", "device_id": "d1", "on": True, **kw}


def test_duty_stores_the_push_token_and_never_echoes_it(client: TestClient, db: FakeFirestore) -> None:
    r = client.post("/duty", json=duty_body(fcm_token="tok-1"))
    assert r.status_code == 200 and "fcm_token" not in r.json()
    assert db.collection("duty").document("blr_j3").get().to_dict()["fcm_token"] == "tok-1"
    client.post(
        "/duty", json=duty_body(device_id="d2")
    )  # the next cop sent none: the old token must not linger
    assert "fcm_token" not in db.collection("duty").document("blr_j3").get().to_dict()
    client.post("/duty", json=duty_body(fcm_token="tok-2"))
    client.post("/duty", json=duty_body(on=False))
    assert "fcm_token" not in db.collection("duty").document("blr_j3").get().to_dict()


# ---- production mode -------------------------------------------------------------------------------------------------


@pytest.fixture
def prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODUCTION_MODE", "1")
    monkeypatch.setenv("DISPATCH_TOKEN", "disp")
    monkeypatch.setenv("AGENCY_KEY", "agency")
    monkeypatch.delenv("DEVICE_TOKENS_DISABLED")  # conftest sets it; production ignores it anyway


def test_demo_mode_leaves_the_demo_calls_open(client: TestClient, seeded: FakeFirestore) -> None:
    assert client.post("/incidents", json={"type": "cardiac"}).status_code == 200
    assert client.post("/vehicles/bind", json={"plate": AMB, "device_id": "d"}).status_code == 200


def test_incidents_need_the_dispatch_token(client: TestClient, db: FakeFirestore, prod: None) -> None:
    body = {"type": "cardiac"}
    assert_envelope(client.post("/incidents", json=body), 401, "dispatch_token_required")
    assert_envelope(
        client.post("/incidents", json=body, headers={"X-Dispatch-Token": "nope"}), 403, "forbidden"
    )
    r = client.post("/incidents", json=body, headers={"X-Dispatch-Token": "disp"})
    assert r.status_code == 200 and r.json()["incident_id"].startswith("INC-")


def test_bind_and_hospital_sign_in_need_the_agency_key(
    client: TestClient, seeded: FakeFirestore, prod: None
) -> None:
    bind = {"plate": AMB, "device_id": "d"}
    r = client.post("/vehicles/bind", json=bind)
    assert_envelope(r, 401, "agency_key_required")
    assert r.headers["X-Request-Id"]  # refused inside the request context: an id and an access line
    assert_envelope(client.post("/vehicles/bind", json=bind, headers={"X-Agency-Key": "x"}), 403, "forbidden")
    assert client.post("/vehicles/bind", json=bind, headers={"X-Agency-Key": "agency"}).status_code == 200
    assert_envelope(client.post("/hospital/duty", json={"hospital_id": "x"}), 401, "agency_key_required")


def test_an_unset_credential_refuses_everything(
    client: TestClient, db: FakeFirestore, prod: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISPATCH_TOKEN")
    assert_envelope(
        client.post("/incidents", json={"type": "x"}, headers={"X-Dispatch-Token": ""}), 403, "forbidden"
    )
    assert_envelope(
        client.post("/incidents", json={"type": "x"}, headers={"X-Dispatch-Token": "a"}), 403, "forbidden"
    )


def test_production_ignores_device_tokens_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import tokens

    monkeypatch.setenv("DEVICE_TOKENS_DISABLED", "1")
    assert tokens.disabled() is True
    monkeypatch.setenv("PRODUCTION_MODE", "1")
    assert tokens.disabled() is False


@pytest.fixture
def desk(client: TestClient, seeded: FakeFirestore, prod: None) -> Callable[[], tuple[str, str, str]]:
    """A run with a log entry and a brief, plus its vehicle token and a hospital desk token."""

    def make() -> tuple[str, str, str]:
        vt = client.post(
            "/vehicles/bind", json={"plate": AMB, "device_id": "d"}, headers={"X-Agency-Key": "agency"}
        ).json()["device_token"]
        ht = client.post(
            "/hospital/duty", json={"hospital_id": "blr_jayadeva"}, headers={"X-Agency-Key": "agency"}
        ).json()["hospital_token"]
        run = seeded.collection("runs").document("run-1")
        run.set({"vehicle_plate": AMB, "state": "en_route"})
        run.collection("log").document("2").set(
            {"t": datetime(2026, 10, 6, tzinfo=UTC), "kind": "voice", "fields": {}}
        )
        run.collection("log").document("10").set(
            {"t": datetime(2026, 10, 6, tzinfo=UTC), "kind": "form", "fields": {}}
        )
        seeded.collection("briefs").document("run-1").set(
            {"summary": "s", "generated_at": datetime(2026, 10, 6, tzinfo=UTC)}
        )
        return "run-1", vt, ht

    return make


def test_log_and_brief_reads_need_a_vehicle_or_desk_token(
    client: TestClient, desk: Callable[[], tuple[str, str, str]]
) -> None:
    rid, vt, ht = desk()
    for path in (f"/runs/{rid}/log", f"/briefs/{rid}"):
        assert_envelope(client.get(path), 401, "device_token_required")
        assert_envelope(client.get(path, headers={"X-Device-Token": "wrong"}), 403, "device_token_mismatch")
        for token in (vt, ht):
            assert client.get(path, headers={"X-Device-Token": token}).status_code == 200
    log_rows = client.get(f"/runs/{rid}/log", headers={"X-Device-Token": ht}).json()
    assert [e["n"] for e in log_rows] == [2, 10] and log_rows[0]["t"].startswith(
        "2026-10-06"
    )  # numeric order, ISO times
    assert client.get(f"/briefs/{rid}", headers={"X-Device-Token": vt}).json()["summary"] == "s"
    assert_envelope(client.get("/runs/nope/log", headers={"X-Device-Token": ht}), 404, "unknown_run")


def test_another_vehicles_token_cannot_read_a_run(
    client: TestClient, desk: Callable[[], tuple[str, str, str]], seeded: FakeFirestore
) -> None:
    rid, _, _ = desk()
    other = client.post(
        "/vehicles/bind", json={"plate": "KA01FE5678", "device_id": "d"}, headers={"X-Agency-Key": "agency"}
    ).json()["device_token"]
    assert_envelope(
        client.get(f"/runs/{rid}/log", headers={"X-Device-Token": other}), 403, "device_token_mismatch"
    )


def test_brief_and_after_action_need_a_token_in_production(
    client: TestClient, desk: Callable[[], tuple[str, str, str]]
) -> None:
    rid, vt, ht = desk()
    assert_envelope(client.post("/brief", json={"run_id": rid}), 401, "device_token_required")
    assert_envelope(
        client.post("/brief", json={"run_id": rid}, headers={"X-Device-Token": vt}),
        403,
        "device_token_mismatch",
    )  # desk only
    assert_envelope(client.post(f"/runs/{rid}/after-action"), 401, "device_token_required")
    assert (
        client.post(f"/runs/{rid}/after-action", headers={"X-Device-Token": ht}).status_code == 409
    )  # past the guard: run not finished
