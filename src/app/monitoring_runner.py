"""python -m app.monitoring_runner [--once]"""

import argparse
import asyncio
import logging

from prometheus_client import start_http_server

from app import config
from app.logging_config import setup_json_logging
from app.models.database import engine
from app.models.schema_check import assert_schema_at_head
from app.monitoring.worker import run, run_once


async def main(once: bool) -> None:
    try:
        await assert_schema_at_head(engine)
        if once:
            await run_once()
        else:
            start_http_server(config.MONITORING_METRICS_PORT)
            await run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate private market monitors")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    setup_json_logging(service="tradingmaster-monitoring", level=getattr(logging, config.LOG_LEVEL, logging.INFO))
    asyncio.run(main(args.once))
