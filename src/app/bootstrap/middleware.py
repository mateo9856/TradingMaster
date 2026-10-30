"""Register middleware from innermost to outermost."""

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app import config
from app.auth import csrf_protect
from app.metrics import http_request_duration_seconds, http_requests_total
from app.middleware.rate_limit import rate_limit_middleware
from app.middleware.security_headers import security_headers_middleware


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



def register_middleware(app: FastAPI) -> None:
    # security headers → CORS → metrics → rate limit → CSRF → router
    app.middleware("http")(csrf_protect)
    app.middleware("http")(rate_limit_middleware)
    FastAPIInstrumentor.instrument_app(app)
    app.middleware("http")(metrics_middleware)
    if config.CORS_ALLOW_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.CORS_ALLOW_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.middleware("http")(security_headers_middleware)
