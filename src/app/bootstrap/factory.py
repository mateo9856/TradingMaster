"""Construct independent FastAPI applications with process-wide observability."""

import logging
from pathlib import Path

from fastapi import FastAPI
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

import app.models  # noqa: F401 — register all ORM models with Base
from app import config
from app.bootstrap.frontend import FRONTEND_DIST, register_frontend
from app.bootstrap.lifespan import lifespan
from app.bootstrap.middleware import register_middleware
from app.bootstrap.routes import register_routes
from app.logging_config import setup_json_logging
from app.models.database import engine
from app.tracing import setup_tracing

_observability_initialized = False


def configure_observability() -> None:
    global _observability_initialized
    if _observability_initialized:
        return
    setup_json_logging(service="tradingmaster-api", level=getattr(logging, config.LOG_LEVEL, logging.INFO))
    setup_tracing(config.OTEL_SERVICE_NAME, config.OTEL_EXPORTER_OTLP_ENDPOINT, enabled=config.OTEL_ENABLED)
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    _observability_initialized = True


def create_app(*, frontend_dist: Path | None = None) -> FastAPI:
    configure_observability()
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

    register_middleware(app)
    register_routes(app)
    register_frontend(app, FRONTEND_DIST if frontend_dist is None else frontend_dist)
    return app
