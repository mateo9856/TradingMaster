import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

import app.config as config
import app.models  # noqa: F401 — registers all ORM models with Base
from app.auth import (
    UserCreate,
    UserRead,
    UserUpdate,
    auth_backend,
    cookie_backend,
    csrf_protect,
    fastapi_users,
)
from app.logging_config import setup_json_logging
from app.metrics import http_request_duration_seconds, http_requests_total
from app.models.database import engine, Base, AsyncSessionLocal
from app.models.seeder import seed_exchanges
from app.kafka.producer import run_producer
from app.routers import exchanges, history, market
from app.tracing import setup_tracing

setup_json_logging(service="tradingmaster-api", level=getattr(logging, config.LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

setup_tracing(config.OTEL_SERVICE_NAME, config.OTEL_EXPORTER_OTLP_ENDPOINT, enabled=config.OTEL_ENABLED)


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

    # The EOD archive job runs as its own process (app/eod_runner.py, driven
    # by cron / a Kubernetes CronJob) rather than an in-process scheduler here
    # — a crashed or redeployed API process should not silently skip a day's
    # archive run. See app/eod_runner.py and k8s/base/eod-cronjob.yaml.

    yield  # API is live

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down...")
    producer_task.cancel()
    try:
        await asyncio.gather(producer_task, return_exceptions=True)
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

# Cross-origin browser access — only used when the UI isn't served from here.
if config.CORS_ALLOW_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ALLOW_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Cookie-authenticated writes must prove they came from our own UI (see
# app/auth/csrf.py). Added after CORS so a blocked request still gets CORS
# headers, and bearer-token clients are never affected.
app.middleware("http")(csrf_protect)

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

# Two login routes for the same accounts: the browser takes the cookie one
# (nothing readable ends up in the page), API clients take the bearer one.
app.include_router(
    fastapi_users.get_auth_router(cookie_backend),
    prefix="/api/v1/auth/cookie",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/api/v1/auth/jwt",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/api/v1/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/api/v1/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/api/v1/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/api/v1/users",
    tags=["users"],
)

if config.PROMETHEUS_METRICS_ENABLED:
    # A route, not app.mount("/metrics", ...): a Mount only matches "/metrics/"
    # and relies on Starlette's redirect for the bare path — and the SPA
    # catch-all below would intercept that redirect, 404-ing the exact path
    # Prometheus scrapes (observability/prometheus/prometheus.yml) and the
    # System screen fetches.
    @app.get("/metrics", include_in_schema=False)
    @app.get("/metrics/", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health", tags=["health"], summary="Liveness check")
async def health():
    return {"status": "ok"}


# ── Front-end (production bundle) ─────────────────────────────────────────────
# Registered last so it can never shadow /api, /docs, /redoc or /metrics. Only
# active once `frontend/dist` has been built (`cd frontend && npm run build`);
# in development the Vite dev server serves the UI and proxies here instead.
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        """
        Serves the built single-page app: a real file when one matches, and
        index.html otherwise, so client-side routes survive a page refresh.
        """
        # An unmatched API path is a genuine 404 — never answer it with the SPA,
        # or a typo'd endpoint would look like a working page to a client.
        if full_path.startswith(("api/", "metrics", "docs", "redoc", "openapi.json")):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(FRONTEND_DIST):
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

    logger.info(f"Serving front-end bundle from {FRONTEND_DIST}")
else:
    logger.info("No front-end bundle found (frontend/dist) — API only")
