"""Device-scoped tokens: no accounts. A bind or a go-on-duty hands the device a random token; only its sha256 is stored."""

import hashlib
import hmac
import os
import secrets


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def mint() -> tuple[str, str]:
    """(token, sha256 to store). 32 random bytes, urlsafe."""
    token = secrets.token_urlsafe(32)
    return token, digest(token)


def disabled() -> bool:
    """DEVICE_TOKENS_DISABLED=1 (offline_replay only): protected calls need no token."""
    return os.environ.get("DEVICE_TOKENS_DISABLED") == "1"


def problem(token: str, hashes: list[str | None]) -> tuple[int, str] | None:
    """None when `token` matches one of the stored hashes (or tokens are disabled); else (status, error code)."""
    if disabled():
        return None
    if not token:
        return 401, "device_token_required"
    mine = digest(token)
    if any(h and hmac.compare_digest(mine, h) for h in hashes):
        return None
    return 403, "device_token_mismatch"
