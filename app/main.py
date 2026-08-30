import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

import app.models  # noqa: F401 — ensures all ORM models register with Base
from app.models.database import engine, Base
from app.kafka.producer import run_producer
from app.routers import market

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("Creating database tables if not exist...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Start Kafka producer as a background task so it doesn't block the API
    logger.info("Starting Kafka producer (exchange streams)...")
    producer_task = asyncio.create_task(run_producer())

    yield  # API is live and serving requests

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down Kafka producer...")
    producer_task.cancel()
    try:
        await producer_task
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


@app.get("/health")
async def health():
    """Quick liveness check."""
    return {"status": "ok"}