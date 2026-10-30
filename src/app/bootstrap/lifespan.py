"""API startup and shutdown, in the same order as the original entrypoint."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.fiat.rates import fiat_rates, watch_fiat_rates
from app.kafka.producer import run_producer
from app.kafka.stream_hub import stream_hub
from app.models.database import AsyncSessionLocal, engine
from app.models.schema_check import assert_schema_at_head
from app.models.seeder import seed_exchanges, seed_instruments
from app.trading.guest import seed_guest

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    # Migrations own the schema (`alembic upgrade head`); the API only checks it.
    # This used to be Base.metadata.create_all, which never altered an existing
    # table — and which all three production replicas ran at once.
    logger.info("Verifying database schema...")
    await assert_schema_at_head()

    # Seed default exchange/symbol config on first run
    logger.info("Seeding exchange and symbol config...")
    async with AsyncSessionLocal() as db:
        await seed_exchanges(db)
        await seed_instruments(db)
        await seed_guest(db)

    # ECB reference rates for the display currencies. Its own task, not part of
    # the producer: prices must still be readable in PLN while Kafka is down
    # (run_producer exits on a Kafka failure and would take the fetcher with it).
    fiat_task = asyncio.create_task(watch_fiat_rates(fiat_rates))

    # Start Kafka producer
    logger.info("Starting Kafka producer (exchange streams)...")
    producer_task = asyncio.create_task(run_producer())

    # The EOD archive job runs as its own process (app/eod_runner.py, driven
    # by cron / a Kubernetes CronJob) rather than an in-process scheduler here
    # — a crashed or redeployed API process should not silently skip a day's
    # archive run. See app/eod_runner.py and k8s/base/eod-cronjob.yaml.

    yield  # API is live

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down...")
    # Stop the shared live-stream consumers before the event loop goes away.
    await stream_hub.close()
    producer_task.cancel()
    fiat_task.cancel()
    try:
        await asyncio.gather(producer_task, fiat_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass

    await engine.dispose()
    logger.info("Shutdown complete")

