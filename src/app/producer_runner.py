import asyncio
import logging

import app.config as config
from app.fiat.rates import fiat_rates, watch_fiat_rates
from app.kafka.producer import run_producer
from app.logging_config import setup_json_logging
from app.tracing import setup_tracing

setup_json_logging(service="tradingmaster-producer", level=getattr(logging, config.LOG_LEVEL, logging.INFO))
setup_tracing(
    "tradingmaster-producer",
    config.OTEL_EXPORTER_OTLP_ENDPOINT,
    enabled=config.OTEL_ENABLED,
)

async def main() -> None:
    # Fiat-quoted markets (Warsaw stocks in PLN) need ECB rates even when no API
    # process runs the fetcher. Running it in both is harmless — inserts ignore
    # rows that already exist.
    fiat_task = asyncio.create_task(watch_fiat_rates(fiat_rates))
    try:
        await run_producer()
    finally:
        fiat_task.cancel()
        await asyncio.gather(fiat_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())