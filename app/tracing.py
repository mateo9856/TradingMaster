"""
OpenTelemetry tracing setup, shared across the FastAPI app and the standalone
producer runner.

setup_tracing() is idempotent — safe to call more than once in the same
process (e.g. if a module gets re-imported under pytest) since it guards
against re-registering the global TracerProvider.
"""

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)

_initialized = False

tracer = trace.get_tracer("tradingmaster")


def setup_tracing(service_name: str, otlp_endpoint: str, enabled: bool = True) -> None:
    """Configures the global TracerProvider to export spans to Jaeger via OTLP."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    if not enabled:
        logger.info("OTel tracing disabled (OTEL_ENABLED=false)")
        return

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)))
    trace.set_tracer_provider(provider)
    logger.info(f"OTel tracing enabled — service={service_name} endpoint={otlp_endpoint}")


def inject_traceparent_headers() -> list[tuple[str, bytes]]:
    """
    Injects the current span's W3C traceparent/tracestate into a carrier dict,
    formatted as aiokafka message headers (list of (str, bytes) tuples).
    """
    carrier: dict[str, str] = {}
    inject(carrier)
    return [(k, v.encode("utf-8")) for k, v in carrier.items()]
