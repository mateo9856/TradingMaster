"""
Structured JSON logging setup, shared across every entrypoint process
(the FastAPI app, the standalone producer runner, and the Flink job).

setup_json_logging() is idempotent — safe to call more than once in the same
process — and must only be called once per process, at its entrypoint
(app/main.py, app/producer_runner.py, app/flink_jobs/candle_builder.py).
Library modules (producer.py, eod_archive.py, routers, etc.) just do
logging.getLogger(__name__) as before and rely on whichever entrypoint
imported them to have already configured the root logger.
"""

import logging

from pythonjsonlogger import json as jsonlogger

try:
    from opentelemetry import trace
except ImportError:  # pragma: no cover — tracing isn't installed in every env
    trace = None

_configured = False


class OtelTraceFilter(logging.Filter):
    """Attaches trace_id/span_id to log records when an OTel span is active."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = None
        record.span_id = None
        if trace is not None:
            span = trace.get_current_span()
            ctx = span.get_span_context()
            if ctx.is_valid:
                record.trace_id = format(ctx.trace_id, "032x")
                record.span_id = format(ctx.span_id, "016x")
        return True


def setup_json_logging(service: str, level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    handler = logging.StreamHandler()
    handler.addFilter(OtelTraceFilter())
    handler.setFormatter(
        jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(trace_id)s %(span_id)s",
            static_fields={"service": service},
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
