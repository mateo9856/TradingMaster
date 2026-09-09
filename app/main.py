import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

import app.models  # noqa: F401 — registers all ORM models with Base
from app.models.database import engine, Base, AsyncSessionLocal
from app.models.seeder import seed_exchanges
from app.kafka.producer import run_producer
from app.jobs.eod_archive import run_eod_job
from app.routers import exchanges, history, market

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def _start_eod_scheduler() -> None:
    """
    Runs the EOD archive job every day at midnight UTC.
    Implemented as a simple async loop — no extra dependencies needed.
    """
    from datetime import datetime, timezone, timedelta

    while True:
        now = datetime.now(timezone.utc)
        # Next midnight UTC
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        wait_seconds = (next_midnight - now).total_seconds()
        logger.info(f"EOD job scheduled in {wait_seconds / 3600:.1f}h (next midnight UTC)")

        await asyncio.sleep(wait_seconds)

        try:
            await run_eod_job()
        except Exception as e:
            logger.error(f"EOD job failed: {e}")


@asynccontextmanager
async def lifespan(application: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("Creating database tables if not exist...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed default exchange/symbol config on first run
    logger.info("Seeding exchange and symbol config...")
    async with AsyncSessionLocal() as db:
        await seed_exchanges(db)

    # Start Kafka producer
    logger.info("Starting Kafka producer (exchange streams)...")
    producer_task = asyncio.create_task(run_producer())

    # Start EOD scheduler
    logger.info("Starting EOD archive scheduler...")
    eod_task = asyncio.create_task(_start_eod_scheduler())

    yield  # API is live

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down...")
    producer_task.cancel()
    eod_task.cancel()
    try:
        await asyncio.gather(producer_task, eod_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass

    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="TradingMaster API",
    version="1.0.0",
    description="Real-time crypto candle data from Binance, Kraken and Coinbase via Kafka + Flink",
    lifespan=lifespan,
)

app.include_router(market.router)
app.include_router(exchanges.router)
app.include_router(history.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
