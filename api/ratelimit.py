"""Per-IP token buckets for the unauthenticated demo endpoints. In memory, so the budget is per Cloud Run instance."""

import math
import os
import time

HEAVY = {"/triage", "/log", "/brief", "/route", "/cop-note"}  # each can start a Gemini, Routes or agent call
PER_MIN = {
    "heavy": 10,
    "general": 60,
    "location": 900,
}  # /location: three simulated vehicles at 20x is 720 a minute
MAX_KEYS = 10_000
_buckets: dict[
    tuple[str, str], tuple[float, float]
] = {}  # (ip, class) -> (tokens, monotonic time of last refill)


def kind(path: str) -> str:
    if path in HEAVY or (path.startswith("/runs/") and path.endswith("/after-action")):
        return "heavy"
    return "location" if path == "/location" else "general"


def retry_after(ip: str, path: str) -> int | None:
    """None: allowed (one token spent). Otherwise the seconds until a token is back."""
    if os.environ.get("RATE_LIMIT_DISABLED") == "1" or path == "/health":
        return None
    k = kind(path)
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
