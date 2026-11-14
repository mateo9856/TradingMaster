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
from hashlib import sha256
from uuid import uuid4

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app import config
from app.metrics import rate_limit_backend_errors_total, rate_limit_rejections_total

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


class RedisSlidingWindowLimiter:
    """Atomic shared sliding windows for API replicas using Redis sorted sets."""

    _SCRIPT = """
    local key = KEYS[1]
    local window = tonumber(ARGV[1])
    local limit = tonumber(ARGV[2])
    local member = ARGV[3]
    local time = redis.call('TIME')
    local now = (tonumber(time[1]) * 1000) + math.floor(tonumber(time[2]) / 1000)
    local cutoff = now - window
    redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
    local count = redis.call('ZCARD', key)
    if count >= limit then
        local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
        local retry = math.max(1, math.ceil((tonumber(oldest[2]) + window - now) / 1000))
        return {0, retry, 0}
    end
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, window)
    return {1, 0, limit - count - 1}
    """

    def __init__(self, window_seconds: float = WINDOW_SECONDS, redis_client=None):
        self._window = window_seconds
        self._redis = redis_client

    async def _client(self):
        if self._redis is None:
            from redis.asyncio import Redis

            self._redis = Redis.from_url(config.RATE_LIMIT_REDIS_URL, decode_responses=True)
        return self._redis

    async def check(self, client: str, bucket: Bucket) -> tuple[bool, int, int]:
        if bucket.limit <= 0:
            return True, 0, 0
        client_hash = sha256(client.encode("utf-8")).hexdigest()
        key = f"tradingmaster:rate-limit:{bucket.name}:{client_hash}"
        result = await (await self._client()).eval(
            self._SCRIPT,
            1,
            key,
            int(self._window * 1000),
            bucket.limit,
            uuid4().hex,
        )
        return bool(int(result[0])), int(result[1]), int(result[2])

    async def close(self) -> None:
        if self._redis is not None:
            close = getattr(self._redis, "aclose", None)
            if close is not None:
                await close()
            self._redis = None


limiter = SlidingWindowLimiter()
shared_limiter = RedisSlidingWindowLimiter()

# Calls between prunes. Cheap insurance against unbounded growth from a wide
# spread of source addresses.
_PRUNE_EVERY = 1000
_calls = 0


def _maybe_prune() -> None:
    global _calls
    _calls += 1
    if _calls % _PRUNE_EVERY == 0:
        limiter.prune()


async def _check(client: str, bucket: Bucket) -> tuple[bool, int, int]:
    if config.RATE_LIMIT_BACKEND == "redis":
        return await shared_limiter.check(client, bucket)
    allowed, retry_after = limiter.check(client, bucket)
    return allowed, retry_after, max(limiter.remaining(client, bucket), 0)


async def check_websocket_connect(websocket) -> tuple[bool, int]:
    """Rate-limit a WebSocket handshake; the HTTP middleware never sees it."""
    if not config.RATE_LIMIT_ENABLED:
        return True, 0
    _maybe_prune()
    bucket = _buckets()["ws"]
    try:
        allowed, retry_after, _ = await _check(client_key(websocket), bucket)
    except Exception:
        rate_limit_backend_errors_total.inc()
        logger.exception("Shared rate-limit backend failed during WebSocket handshake")
        return False, 1
    if not allowed:
        rate_limit_rejections_total.labels(bucket=bucket.name).inc()
    return allowed, retry_after


async def rate_limit_middleware(request: Request, call_next):
    if not config.RATE_LIMIT_ENABLED or request.url.path in EXEMPT_PATHS:
        return await call_next(request)

    _maybe_prune()
    bucket = _buckets()[bucket_for(request.method, request.url.path)]
    client = client_key(request)
    try:
        allowed, retry_after, remaining = await _check(client, bucket)
    except Exception:
        rate_limit_backend_errors_total.inc()
        logger.exception("Shared rate-limit backend unavailable; failing closed")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Request limiting is temporarily unavailable; retry shortly."},
            headers={"Retry-After": "1"},
        )

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
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response


async def close_rate_limit_backend() -> None:
    await shared_limiter.close()
