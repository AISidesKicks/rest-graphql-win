"""OpenTelemetry wiring.

The lab writes spans into ``scratch/traces/*.jsonl`` with a tiny custom
exporter, so the traces stay readable without a collector. If
``OTEL_EXPORTER_OTLP_ENDPOINT`` is set the same spans are also shipped to an
OTLP backend, which is how Arize Phoenix picks them up.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode

_STATE = threading.local()
_PROVIDER: TracerProvider | None = None


class JsonlSpanExporter(SpanExporter):
    """Write spans as one JSON object per line."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def export(self, spans: tuple[ReadableSpan, ...]) -> SpanExportResult:
        lines = []
        for span in spans:
            lines.append(json.dumps(span_to_dict(span), ensure_ascii=False))
        payload = "\n".join(lines) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(payload)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def _attr_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_attr_value(item) for item in value]
    return str(value)


def span_to_dict(span: ReadableSpan) -> dict[str, Any]:
    """Flatten a span into a plain dict, the shape the lab docs show."""
    context = span.get_span_context()
    parent = span.parent
    attributes = {key: _attr_value(value) for key, value in (span.attributes or {}).items()}
    status: dict[str, Any] = {"code": span.status.status_code.name}
    if span.status.description:
        status["description"] = span.status.description
    return {
        "name": span.name,
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
        "parent_span_id": format(parent.span_id, "016x") if parent else None,
        "start_time": datetime.fromtimestamp(span.start_time / 1e9, tz=UTC).isoformat(),
        "end_time": datetime.fromtimestamp(span.end_time / 1e9, tz=UTC).isoformat(),
        "duration_ms": round((span.end_time - span.start_time) / 1e6, 3),
        "attributes": attributes,
        "status": status,
        "events": [
            {
                "name": event.name,
                "timestamp": datetime.fromtimestamp(event.timestamp / 1e9, tz=UTC).isoformat(),
                "attributes": {k: _attr_value(v) for k, v in (event.attributes or {}).items()},
            }
            for event in span.events
        ],
    }


def setup_tracing(
    service_name: str = "rest-graphql-lab",
    traces_dir: Path | None = None,
    otlp_endpoint: str | None = None,
    enabled: bool = True,
) -> TracerProvider | None:
    """Install the tracer provider, once per process."""
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    if not enabled:
        trace.set_tracer_provider(trace.NoOpTracerProvider())
        return None

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if traces_dir is not None:
        traces_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
        provider.add_span_processor(
            SimpleSpanProcessor(JsonlSpanExporter(traces_dir / f"trace-{stamp}.jsonl"))
        )

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            SimpleSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True))
        )

    trace.set_tracer_provider(provider)
    _PROVIDER = provider
    return provider


def get_tracer(name: str = "rest-graphql-lab") -> trace.Tracer:
    return trace.get_tracer(name)


def shutdown_tracing() -> None:
    global _PROVIDER
    if _PROVIDER is not None:
        _PROVIDER.shutdown()
        _PROVIDER = None


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """Start a span, record exceptions and set the status automatically."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, _attr_value(value))
        try:
            yield current
        except Exception as exc:
            current.record_exception(exc)
            current.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def record_sql(current: trace.Span, sql: str, params: Any = None, rowcount: int | None = None) -> None:
    """Attach the SQL text to the current span."""
    current.set_attribute("db.statement", sql)
    if params is not None:
        current.set_attribute("db.params", repr(params))
    if rowcount is not None:
        current.set_attribute("db.rowcount", rowcount)
