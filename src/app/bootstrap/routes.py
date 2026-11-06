"""API, authentication, health, metrics and search-engine endpoints."""

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import config, seo
from app.auth import (
    UserCreate,
    UserRead,
    UserUpdate,
    auth_backend,
    cookie_backend,
    fastapi_users,
)
from app.jobs.job_metrics import refresh_job_metrics
from app.models.database import AsyncSessionLocal
from app.routers import (
    currencies,
    exchanges,
    history,
    instruments,
    market,
    monitoring,
    trading,
)
from app.routers.market import load_markets


def register_routes(app: FastAPI) -> None:
    app.include_router(market.router)
    app.include_router(exchanges.router)
    app.include_router(history.router)
    app.include_router(currencies.router)
    app.include_router(instruments.router)
    app.include_router(trading.router)
    app.include_router(monitoring.router)

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


    # ── Search engines ────────────────────────────────────────────────────────────

    @app.get("/robots.txt", include_in_schema=False)
    async def robots(request: Request) -> PlainTextResponse:
        return PlainTextResponse(seo.robots_txt(seo.site_url(request)))


    @app.get("/sitemap.xml", include_in_schema=False)
    async def sitemap(request: Request) -> Response:
        """Every indexable page in every language, with hreflang alternates."""
        async with AsyncSessionLocal() as db:
            markets = await load_markets(db)
        body = seo.sitemap_xml(seo.site_url(request), [m.slug for m in markets if m.slug])
        return Response(body, media_type="application/xml")
