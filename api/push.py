"""Web push to the cop on duty. When an alert is written for junction J and duty/{J} holds an `fcm_token` (sent with
POST /duty), the alert text and audio_url go out as one FCM message with a notification and a data payload, so the phone
rings with the screen off. Free tier. Every failure is logged, never raised: the alert itself is already stored."""

from typing import Any

from google.cloud.firestore import DELETE_FIELD

from firestore_client import db
from logctx import log
from telemetry import span

TTL_S = "120"  # an alert older than two minutes is history (the cop page stops speaking it too)


def _messaging() -> Any:
    """firebase_admin.messaging on Application Default Credentials (the Cloud Run service account); imported lazily."""
    import firebase_admin
    from firebase_admin import messaging

    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    return messaging


def build(messaging: Any, token: str, alert: dict, run_id: str, n: str, audio_url: str | None) -> Any:
    text = alert.get("text_local") or alert.get("text") or ""
    data = {
        "run_id": run_id,
        "alert_n": n,
        "junction_id": alert.get("junction_id") or "",
        "stage": alert.get("stage") or "",
        "text": text,
        "audio_url": audio_url or "",
    }
    return messaging.Message(
        token=token,
        notification=messaging.Notification(
            title=f"{alert.get('stage', 'ALERT')} · emergency vehicle", body=text
        ),
        data=data,
        webpush=messaging.WebpushConfig(
            headers={"Urgency": "high", "TTL": TTL_S},
            fcm_options=messaging.WebpushFCMOptions(link="/cop"),
        ),
    )


def send_alert(alert_ref: Any, audio_url: str | None) -> bool:
    """Push the alert at `alert_ref` (runs/{run}/alerts/{n}) to the cop on duty at its junction. True when FCM accepted it."""
    try:
        alert = alert_ref.get().to_dict() or {}
        jid = alert.get("junction_id")
        duty = db.collection("duty").document(jid or "-").get().to_dict() or {}
        token = duty.get("fcm_token") if duty.get("on") else None
        if not token:
            return False
        messaging = _messaging()
        run_id, n = alert_ref.path.split("/")[1], alert_ref.id  # runs/{run}/alerts/{n}
        try:
            with span("push.send", junction_id=jid):
                messaging.send(build(messaging, token, alert, run_id, n, audio_url))
        except Exception as e:
            if type(e).__name__ in (
                "UnregisteredError",
                "SenderIdMismatchError",
            ):  # the browser dropped the subscription
                db.collection("duty").document(jid).update({"fcm_token": DELETE_FIELD})
            raise
        log(event="push_sent", run_id=run_id, junction_id=jid, alert_n=n)
        return True
    except Exception as e:
        log(event="push_error", error=type(e).__name__, detail=str(e)[:200])
        return False
