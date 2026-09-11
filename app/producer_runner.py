import asyncio
import logging

import app.config as config
from app.kafka.producer import run_producer
from app.logging_config import setup_json_logging
from app.tracing import setup_tracing

setup_json_logging(service="tradingmaster-producer", level=getattr(logging, config.LOG_LEVEL, logging.INFO))
setup_tracing(
    "tradingmaster-producer",
    config.OTEL_EXPORTER_OTLP_ENDPOINT,
    enabled=config.OTEL_ENABLED,
)

if __name__ == "__main__":
    asyncio.run(run_producer())