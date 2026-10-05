"""Structured JSON log lines; every line carries the current request's id."""

import json
from contextvars import ContextVar
from typing import Any

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def log(**kw: Any) -> None:
    rid = request_id.get()
    if rid:
        kw.setdefault("request_id", rid)
    print(json.dumps(kw, default=str), flush=True)
