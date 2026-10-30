"""
In-process rate limiting.

There was none at all before this: `/api/v1/auth/cookie/login`,
`/api/v1/auth/jwt/login`, `/api/v1/auth/register` and
`/api/v1/auth/forgot-password` could be hit as fast as a client could manage,
which is the whole of the brute-force defence on an account that can
reconfigure exchanges and insert prices.

Sliding-window counters per (client, bucket), held in this process. With
several API replicas the effective limit is roughly the configured value times
the replica count. That is a deliberate trade: it bounds abuse without adding
Redis to the deployment, and the limits below are set for abuse protection, not
for precise quota enforcement. Per-user quotas (roadmap #18) would need shared
state.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app import config
from app.metrics import rate_limit_rejections_total

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60.0

# Never rate-limited: Prometheus scrapes /metrics every 15s, and the liveness
# probe must never be told to back off.
EXEMPT_PATHS = frozenset({"/health", "/metrics", "/metrics/"})

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Bucket:
    name: str
    limit: int


def _buckets() -> dict[str, Bucket]:
    """Read limits from config at call time so tests can patch them."""
    return {
        "auth":    Bucket("auth", config.RATE_LIMIT_AUTH_PER_MINUTE),
        "archive": Bucket("archive", config.RATE_LIMIT_ARCHIVE_PER_MINUTE),
        "write":   Bucket("write", config.RATE_LIMIT_WRITE_PER_MINUTE),
        "read":    Bucket("read", config.RATE_LIMIT_READ_PER_MINUTE),
        "ws":      Bucket("ws", config.RATE_LIMIT_WS_CONNECT_PER_MINUTE),
    }


def client_key(request_or_scope) -> str:
    """
    The address a limit is counted against.

    X-Forwarded-For is honoured only when TRUST_PROXY_HEADERS says a proxy is
    rewriting it. Trusting it unconditionally would let any client send a
    random value per request and never hit a per-IP limit at all.
    """
    headers = request_or_scope.headers
    client = getattr(request_or_scope, "client", None)

    if config.TRUST_PROXY_HEADERS:
        forwarded = headers.get("x-forwarded-for")
        if forwarded:
            # Left-most entry is the original client; the proxy appends itself.
            return forwarded.split(",")[0].strip()

    return client.host if client and client.host else "unknown"


def bucket_for(method: str, path: str) -> str:
    if path.startswith("/api/v1/auth/") or path.startswith("/api/v1/users"):
        # Covers login, register, forgot-password, reset-password and verify.
        if method not in SAFE_METHODS:
            return "auth"
    if path.startswith("/api/v1/history/archive/") and method == "POST":
        return "archive"
    return "read" if method in SAFE_METHODS else "write"


class SlidingWindowLimiter:
    """Per-(client, bucket) request timestamps inside a rolling window."""

    def __init__(self, window_seconds: float = WINDOW_SECONDS):
        self._window = window_seconds
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(self, client: str, bucket: Bucket, now: float | None = None) -> tuple[bool, int]:
        """
        Record an attempt. Returns (allowed, retry_after_seconds).

        A rejected attempt is not recorded, so a client hammering the endpoint
        cannot keep extending its own penalty window indefinitely.
        """
        if bucket.limit <= 0:
            return True, 0

        now = time.monotonic() if now is None else now
        hits = self._hits[(client, bucket.name)]

        cutoff = now - self._window
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= bucket.limit:
            retry_after = max(1, int(hits[0] + self._window - now) + 1)
            return False, retry_after

        hits.append(now)
        return True, 0

    def remaining(self, client: str, bucket: Bucket) -> int:
        hits = self._hits.get((client, bucket.name))
        return bucket.limit - len(hits) if hits else bucket.limit

    def prune(self, now: float | None = None) -> None:
        """Drop windows that have fully expired, so the map can't grow forever."""
        now = time.monotonic() if now is None else now
        cutoff = now - self._window
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            self._hits.pop(key, None)

    def reset(self) -> None:
        self._hits.clear()


limiter = SlidingWindowLimiter()

# Calls between prunes. Cheap insurance against unbounded growth from a wide
# spread of source addresses.
_PRUNE_EVERY = 1000
_calls = 0


def _maybe_prune() -> None:
    global _calls
    _calls += 1
    if _calls % _PRUNE_EVERY == 0:
        limiter.prune()


def check_websocket_connect(websocket) -> tuple[bool, int]:
    """Rate-limit a WebSocket handshake; the HTTP middleware never sees it."""
    if not config.RATE_LIMIT_ENABLED:
        return True, 0
    _maybe_prune()
    bucket = _buckets()["ws"]
    allowed, retry_after = limiter.check(client_key(websocket), bucket)
    if not allowed:
        rate_limit_rejections_total.labels(bucket=bucket.name).inc()
    return allowed, retry_after


async def rate_limit_middleware(request: Request, call_next):
    if not config.RATE_LIMIT_ENABLED or request.url.path in EXEMPT_PATHS:
        return await call_next(request)

    _maybe_prune()
    bucket = _buckets()[bucket_for(request.method, request.url.path)]
    client = client_key(request)
    allowed, retry_after = limiter.check(client, bucket)

    if not allowed:
        rate_limit_rejections_total.labels(bucket=bucket.name).inc()
        logger.warning(
            f"Rate limited {request.method} {request.url.path} "
            f"(bucket={bucket.name}, limit={bucket.limit}/min)"
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": (
                    f"Too many requests. This endpoint allows {bucket.limit} per minute; "
                    f"retry in {retry_after}s."
                )
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(bucket.limit),
                "X-RateLimit-Remaining": "0",
            },
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(bucket.limit)
    response.headers["X-RateLimit-Remaining"] = str(max(limiter.remaining(client, bucket), 0))
    return response
