"""Structured JSON log lines; every line carries the current request's id, and the trace id when tracing is on."""

import json
import os
from contextvars import ContextVar
from typing import Any

import telemetry

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def log(**kw: Any) -> None:
    rid = request_id.get()
    if rid:
        kw.setdefault("request_id", rid)
    if tid := telemetry.trace_id():
        kw.setdefault("trace_id", tid)
        # the key Cloud Logging reads to link a log line to its trace
        kw.setdefault(
            "logging.googleapis.com/trace", f"projects/{os.environ.get('GCP_PROJECT', '-')}/traces/{tid}"
        )
    print(json.dumps(kw, default=str), flush=True)
