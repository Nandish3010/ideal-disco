"""Cop voice back-channel: what a constable's report does. Gemini only fills {kind, extra_seconds, reason, transcript_en}
(gemini.cop_note); every effect below is a plain rule, so a misheard report can at worst extend a green by 3 minutes."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import BackgroundTasks
from google.cloud.firestore import transactional
from google.cloud.firestore_v1.base_query import FieldFilter

import replanner
from logctx import log

KINDS = {"delay", "cleared", "cannot_clear", "other"}
MAX_EXTRA_S = 180  # a delay extends the green by at most this
DEFAULT_EXTRA_S = 60  # a delay with no usable time said
ESCALATE_OVER_S = 90  # a delay longer than this escalates the alert
BLOCK_S = 300  # cannot_clear: /location doubles the junction's clear time for this long
AUDIT = {
    "delay": "cop_delay",
    "cleared": "cop_cleared",
    "cannot_clear": "cop_cannot_clear",
    "other": "cop_note",
}


def normalise(raw: dict) -> dict:
    """The model's reply made safe to act on: known kind, a capped positive time for a delay only, short text."""
    kind = raw.get("kind") if raw.get("kind") in KINDS else "other"
    extra = raw.get("extra_seconds")
    if kind == "delay":
        extra = min(extra if isinstance(extra, int) and extra > 0 else DEFAULT_EXTRA_S, MAX_EXTRA_S)
    else:
        extra = None
    return {
        "kind": kind,
        "extra_seconds": extra,
        "reason": str(raw.get("reason") or "").strip()[:80],
        "transcript_en": str(raw.get("transcript_en") or "").strip()[:500],
    }


def next_n(db, ref) -> int:
    """The junction's next note number, 0-based, bumped inside one transaction on duty/{..}.note_count."""
    if not ref.get().exists:  # only with DEVICE_TOKENS_DISABLED: nobody went on duty first
        ref.set({"on": False})

    @transactional
    def bump(tx):
        n = (ref.get(transaction=tx).to_dict() or {}).get("note_count", 0)
        tx.update(ref, {"note_count": n + 1})
        return n

    return bump(db.transaction())


def alerts_ahead(db, jid: str) -> list[Any]:
    """Alerts at this junction of the runs still heading for it, newest first."""
    found: list[Any] = []
    for r in (
        db.collection("runs").where(filter=FieldFilter("ahead_ids", "array_contains", jid)).limit(20).stream()
    ):
        if (r.to_dict() or {}).get("state") == "en_route":
            found += list(
                r.reference.collection("alerts").where(filter=FieldFilter("junction_id", "==", jid)).stream()
            )
    return sorted(
        found, key=lambda a: a.to_dict().get("created_at") or datetime.min.replace(tzinfo=UTC), reverse=True
    )


def duration(s: int) -> str:
    return f"{s // 60} min" if s % 60 == 0 else f"{s} s"


def apply(db, jid: str, raw: dict, now: datetime, bg: BackgroundTasks | None = None) -> dict[str, Any]:
    """Store the note and act on it. jid is `blr_j3`. Returns what the cop page shows. A cannot_clear or a delay over 90 s
    also schedules the re-planner on `bg` once the rule effects above are written (replanner.run, which never raises)."""
    note = normalise(raw)
    kind, extra = note["kind"], note["extra_seconds"]
    duty_ref = db.collection("duty").document(jid)
    jref = db.collection("junctions").document(jid)
    n = next_n(db, duty_ref)
    alerts = alerts_ahead(db, jid)
    unacked = next(
        (a for a in alerts if not a.to_dict().get("acked_at")), None
    )  # what "cleared" acknowledges and an escalation flags: an acknowledged alert is never escalated
    target = unacked
    unacked_path, target_path = (x.reference.path if x else None for x in (unacked, target))
    fx: dict[str, Any] = {"phase_extended_s": 0, "acked": 0, "escalated": 0, "blocked_s": 0}
    why = {"delay": "cop_reported_delay", "cannot_clear": "cop_cannot_clear"}.get(kind)
    # flagged once: an alert the 20 s timer already escalated is left alone
    esc = (
        target is not None
        and (kind == "cannot_clear" or (kind == "delay" and extra > ESCALATE_OVER_S))
        and not target.to_dict().get("escalated")
    )

    if kind == "delay":
        phase = (jref.get().to_dict() or {}).get("phase") or {}
        if phase.get("until") and phase["until"] > now:
            jref.update({"phase.until": phase["until"] + timedelta(seconds=extra)})
            fx["phase_extended_s"] = extra
    elif kind == "cannot_clear":
        jref.set({"cop_block_until": now + timedelta(seconds=BLOCK_S)}, merge=True)
        if (jref.get().to_dict() or {}).get("phase"):
            jref.update({"phase.blocked": True})
        fx["blocked_s"] = BLOCK_S

    cop_note = {**note, "junction_id": jid, "n": n, "at": now}
    for a in alerts:
        d = a.to_dict()
        upd: dict[str, Any] = {"cop_note": cop_note}
        if kind == "delay":
            upd["cop_delay_s"] = (d.get("cop_delay_s") or 0) + extra
        if a.reference.path == unacked_path and kind == "cleared":
            created = d.get("created_at")
            upd.update(
                {
                    "acked_at": now,
                    "ack_latency_s": round(max((now - created).total_seconds(), 0), 1) if created else None,
                    "acked_by": "cop-note",
                }
            )
            fx["acked"] = 1
        if esc and a.reference.path == target_path:
            upd.update({"escalated": True, "escalated_at": now, "escalation_reason": why})
            fx["escalated"] = 1
            db.collection("audit").add(
                {
                    "run_id": a.reference.path.split("/")[1],
                    "junction_id": jid,
                    "action": "escalation",
                    "alert_n": int(a.id),
                    "stage": d.get("stage"),
                    "reason": why,
                    "at": now,
                }
            )
        a.reference.update(upd)

    device = (duty_ref.get().to_dict() or {}).get("device_id")
    db.collection("audit").add(
        {
            "junction_id": jid,
            "action": AUDIT[kind],
            "note_n": n,
            "extra_seconds": extra,
            "reason": note["reason"],
            "run_ids": [a.reference.path.split("/")[1] for a in alerts],
            "device_id": device,
            "at": now,
        }
    )
    duty_ref.collection("notes").document(str(n)).set({**note, "t": now, "device_id": device, "effects": fx})
    log(event="cop_note", junction_id=jid, kind=kind, extra_seconds=extra, **fx)
    run_ids = sorted({a.reference.path.split("/")[1] for a in alerts})
    trigger = kind == "cannot_clear" or (kind == "delay" and (extra or 0) > ESCALATE_OVER_S)
    if bg and run_ids and trigger and not replanner.disabled():
        bg.add_task(replanner.run, jid, n, note, run_ids)
    return {**note, "n": n, "effects": fx, "action_text": action_text(kind, extra, fx)}


def action_text(kind: str, extra: int | None, fx: dict) -> str:
    if kind == "delay":
        text = (
            f"Green extended by {duration(fx['phase_extended_s'])}"
            if fx["phase_extended_s"]
            else f"Delay of {duration(extra or 0)} noted, no green to extend"
        )
        return text + (", escalated" if fx["escalated"] else "")
    if kind == "cleared":
        return "Alert acknowledged" if fx["acked"] else "Junction clear noted, no open alert"
    if kind == "cannot_clear":
        return "Escalated: junction cannot clear, earlier warnings for the next 5 min"
    return "Noted"
