import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from prometheus_client import make_asgi_app

import app.config as config
import app.models  # noqa: F401 — registers all ORM models with Base
from app.logging_config import setup_json_logging
from app.metrics import http_request_duration_seconds, http_requests_total
from app.models.database import engine, Base, AsyncSessionLocal
from app.models.seeder import seed_exchanges
from app.kafka.producer import run_producer
from app.jobs.eod_archive import run_eod_job
from app.routers import exchanges, history, market
from app.tracing import setup_tracing

setup_json_logging(service="tradingmaster-api", level=getattr(logging, config.LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

setup_tracing(config.OTEL_SERVICE_NAME, config.OTEL_EXPORTER_OTLP_ENDPOINT, enabled=config.OTEL_ENABLED)


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
    docs_url="/docs",
    redoc_url="/redoc"
)

FastAPIInstrumentor.instrument_app(app)
SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    path = request.url.path
    http_requests_total.labels(method=request.method, path=path, status_code=response.status_code).inc()
    http_request_duration_seconds.labels(method=request.method, path=path).observe(duration)
    return response


app.include_router(market.router)
app.include_router(exchanges.router)
app.include_router(history.router)

if config.PROMETHEUS_METRICS_ENABLED:
    app.mount("/metrics", make_asgi_app())


@app.get("/health", tags=["health"], summary="Liveness check")
async def health():
    return {"status": "ok"}
