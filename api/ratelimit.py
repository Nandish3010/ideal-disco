"""Per-IP limits for the unauthenticated demo endpoints. Fixed one-minute windows counted in Firestore
(`ratelimits/{bucket}:{ip}:{window}`), so every Cloud Run instance spends one shared budget. If Firestore errors, a
per-instance in-memory token bucket takes over (`ratelimit_fallback` is logged)."""

import math
import os
import time
from datetime import UTC, datetime

from google.cloud.firestore import Increment, transactional

from firestore_client import db
from logctx import log

HEAVY = {"/triage", "/log", "/brief", "/route", "/cop-note"}  # each can start a Gemini, Routes or agent call
PER_MIN = {
    "heavy": 10,
    "general": 60,
    "location": 900,
}  # /location: three simulated vehicles at 20x is 720 a minute
WINDOW_S = 60
FALLBACK_S = 30  # after a Firestore error, go straight to memory this long instead of paying the failure on every request
MAX_KEYS = 10_000
_buckets: dict[
    tuple[str, str], tuple[float, float]
] = {}  # (ip, class) -> (tokens, monotonic time of last refill)
_down_until = 0.0  # monotonic time before which Firestore is not tried


def kind(path: str) -> str:
    if path in HEAVY or (path.startswith("/runs/") and path.endswith("/after-action")):
        return "heavy"
    return "location" if path == "/location" else "general"


def _shared(ip: str, k: str) -> int | None:
    """One Firestore transaction on this window's counter: None = allowed (count bumped), else seconds to the next window.
    ponytail: a single hot document takes about one write a second sustained, so a client past that contends and drops to the
    in-memory limiter (max_attempts=2); shard the counter by a suffix if that ever matters."""
    now = time.time()
    window = int(now // WINDOW_S)
    ref = db.collection("ratelimits").document(f"{k}:{ip[:64].replace('/', '_')}:{window}")
    rate = PER_MIN[k]

    @transactional  # built per call: the wrapper keeps retry state
    def spend(tx):
        if (ref.get(transaction=tx).to_dict() or {}).get("count", 0) >= rate:
            return False
        # expires_at is the field a Firestore TTL policy on `ratelimits` deletes by: two windows after this one started
        tx.set(
            ref,
            {"count": Increment(1), "expires_at": datetime.fromtimestamp((window + 2) * WINDOW_S, UTC)},
            merge=True,
        )
        return True

    if spend(db.transaction(max_attempts=2)):
        return None
    return max(1, math.ceil((window + 1) * WINDOW_S - now))


def _local(ip: str, k: str) -> int | None:
    rate = PER_MIN[k]
    now = time.monotonic()
    tokens, last = _buckets.get((ip, k), (float(rate), now))
    tokens = min(float(rate), tokens + (now - last) * rate / 60)
    if (
        len(_buckets) > MAX_KEYS
    ):  # ponytail: wipe instead of evicting; a scanner only resets everyone's budget
        _buckets.clear()
    if tokens >= 1:
        _buckets[(ip, k)] = (tokens - 1, now)
        return None
    _buckets[(ip, k)] = (tokens, now)
    return math.ceil((1 - tokens) * 60 / rate)


def retry_after(ip: str, path: str) -> int | None:
    """None: allowed (one unit spent). Otherwise the seconds until the caller may try again. Blocking (Firestore I/O):
    async callers run it in a thread."""
    global _down_until
    if os.environ.get("RATE_LIMIT_DISABLED") == "1" or path == "/health":
        return None
    k = kind(path)
    if time.monotonic() >= _down_until:
        try:
            return _shared(ip, k)
        except Exception as e:
            # a limiter must never turn into an outage: any store error means "count locally"
            _down_until = time.monotonic() + FALLBACK_S
            log(event="ratelimit_fallback", error=type(e).__name__, detail=str(e)[:200])
    return _local(ip, k)
