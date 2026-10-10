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
from app.jobs.job_metrics import refresh_job_metrics
from app.kafka.stream_hub import stream_hub
from app.logging_config import setup_json_logging
from app.middleware.rate_limit import rate_limit_middleware
from app.middleware.security_headers import security_headers_middleware
from app.metrics import http_request_duration_seconds, http_requests_total
from app.models.database import engine, AsyncSessionLocal
from app.models.schema_check import assert_schema_at_head
from app.models.seeder import seed_exchanges
from app.fiat.rates import fiat_rates, watch_fiat_rates
from app.kafka.producer import run_producer
from app.routers import currencies, exchanges, history, market
from app.tracing import setup_tracing

setup_json_logging(service="tradingmaster-api", level=getattr(logging, config.LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

setup_tracing(config.OTEL_SERVICE_NAME, config.OTEL_EXPORTER_OTLP_ENDPOINT, enabled=config.OTEL_ENABLED)


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


app = FastAPI(
    title="TradingMaster API",
    version="1.0.0",
    description="Real-time crypto candle data from Binance, Kraken and Coinbase via Kafka + Flink",
    lifespan=lifespan,
    # Interactive docs are useful for a public data API, but they also publish
    # the full endpoint surface — the production overlay sets DOCS_ENABLED=false.
    docs_url="/docs" if config.DOCS_ENABLED else None,
    redoc_url="/redoc" if config.DOCS_ENABLED else None,
    openapi_url="/openapi.json" if config.DOCS_ENABLED else None,
)

# ── Middleware ────────────────────────────────────────────────────────────────
# Starlette builds the stack from `reversed(user_middleware)` and each
# registration inserts at the front, so the LAST one registered here ends up
# OUTERMOST at request time. Registering in the order below gives, from the
# outside in:
#
#   security headers → CORS → metrics → rate limit → CSRF → router
#
# CORS has to sit *outside* CSRF. CORSMiddleware adds
# Access-Control-Allow-Origin to the response on the way back out, so it only
# sees a response produced deeper in the stack. With CORS innermost — which is
# what the old registration order actually produced, despite a comment claiming
# the opposite — a CSRF 403 (and now a 429) carried no CORS headers at all, and
# a cross-origin UI saw an opaque network error instead of the real reason.
#
# Security headers are outermost so they land on every response, including the
# ones short-circuited by the layers below.

# Cookie-authenticated writes must prove they came from our own UI (app/auth/csrf.py).
app.middleware("http")(csrf_protect)

# Brute-force and abuse protection, outside CSRF so rejected writes are counted.
app.middleware("http")(rate_limit_middleware)

FastAPIInstrumentor.instrument_app(app)
SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    # The matched route template ("/api/v1/market/candles/{ticker}"), not the
    # raw URL. Labelling by raw path gave every distinct URL — including every
    # 404 an anonymous client cared to invent — its own Prometheus time series,
    # which grows without bound and bloats the /metrics response.
    route = request.scope.get("route")
    path = getattr(route, "path_format", None) or getattr(route, "path", None) or "<unmatched>"

    http_requests_total.labels(method=request.method, path=path, status_code=response.status_code).inc()
    http_request_duration_seconds.labels(method=request.method, path=path).observe(duration)
    return response


# Cross-origin browser access — only used when the UI isn't served from here.
# Registered after the layers it must wrap (see the ordering note above).
if config.CORS_ALLOW_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ALLOW_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Registered last, so it wraps everything above and sets headers even on a
# response short-circuited by the rate limiter or the CSRF check.
app.middleware("http")(security_headers_middleware)


app.include_router(market.router)
app.include_router(exchanges.router)
app.include_router(history.router)
app.include_router(currencies.router)

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
        # The EOD archive runs in its own short-lived process that Prometheus
        # never scrapes, so its outcome is read from the job_runs table here.
        # refresh_job_metrics never raises — a database problem must not cost
        # us every other metric on the endpoint.
        await refresh_job_metrics()
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
