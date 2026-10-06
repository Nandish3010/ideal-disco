"""Cloud Trace via OpenTelemetry, on when OTEL_ENABLED=1; with it unset every function here is a no-op and no
OpenTelemetry package is imported. FastAPI requests and every httpx call (Gemini through google-genai, Routes) become
spans automatically; the engine steps and the gRPC Text-to-Speech call get manual spans (`leadtime`, `priority`,
`brief`, `agent.route`, `tts`)."""

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Any

_tracer: Any = None


def enabled() -> bool:
    return os.environ.get("OTEL_ENABLED") == "1"


def setup(app: Any) -> bool:
    """Install the Cloud Trace exporter and the FastAPI and httpx instrumentation. Returns whether tracing is on; a
    failure is logged and leaves the service running untraced. Call it after the app's middleware is registered so the
    request span is the outermost one and every log line, the access line included, carries its trace id."""
    global _tracer
    if not enabled():
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        ratio = float(os.environ.get("OTEL_SAMPLE_RATIO", "1"))
        provider = TracerProvider(
            resource=Resource.create({"service.name": os.environ.get("K_SERVICE", "corridor-api")}),
            sampler=ParentBased(TraceIdRatioBased(ratio)),
        )
        provider.add_span_processor(
            BatchSpanProcessor(CloudTraceSpanExporter(project_id=os.environ.get("GCP_PROJECT")))
        )
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(
            app, tracer_provider=provider, excluded_urls="health", exclude_spans=["receive", "send"]
        )
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
        _tracer = provider.get_tracer("corridor-api")
    except Exception as e:  # tracing must never stop the API from starting
        from logctx import log

        log(event="otel_setup_failed", error=type(e).__name__, detail=str(e)[:200])
        return False
    return True


def trace_id() -> str | None:
    """Hex trace id of the current span, None when tracing is off or no span is active."""
    if _tracer is None:
        return None
    from opentelemetry import trace

    ctx = trace.get_current_span().get_span_context()
    return f"{ctx.trace_id:032x}" if ctx.is_valid else None


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[Any]:
    """A child span of the current one; does nothing when tracing is off."""
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as s:
        for k, v in attrs.items():
            s.set_attribute(k, v)
        yield s


def traced(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator form of span(): wraps each call of the function in a span called `name`."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*a: Any, **kw: Any) -> Any:
            with span(name):
                return fn(*a, **kw)

        return wrapper

    return deco
