"""
API hardening, end to end: rate limiting, bounded inputs, security headers and
the middleware ordering the CSRF defence depends on.
"""

from unittest.mock import patch

import pytest

from app import config
from app.middleware.rate_limit import limiter


# ── Rate limiting ────────────────────────────────────────────────────────────

async def test_login_attempts_are_rate_limited(anonymous_client):
    """
    Brute-force protection. `/auth/*` had no limit at all, so an attacker could
    try passwords as fast as the network allowed.
    """
    limiter.reset()
    with patch.object(config, "RATE_LIMIT_AUTH_PER_MINUTE", 3):
        statuses = [
            (await anonymous_client.post(
                "/api/v1/auth/jwt/login",
                data={"username": "nobody@example.com", "password": "wrong-password-x"},
            )).status_code
            for _ in range(5)
        ]

    assert statuses[-1] == 429
    assert statuses.count(429) == 2


async def test_a_rate_limited_response_says_when_to_retry(anonymous_client):
    limiter.reset()
    with patch.object(config, "RATE_LIMIT_AUTH_PER_MINUTE", 1):
        await anonymous_client.post(
            "/api/v1/auth/jwt/login", data={"username": "a@b.com", "password": "xxxxxxxxxxxx"}
        )
        response = await anonymous_client.post(
            "/api/v1/auth/jwt/login", data={"username": "a@b.com", "password": "xxxxxxxxxxxx"}
        )

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert response.headers["X-RateLimit-Limit"] == "1"


async def test_reads_are_not_limited_by_the_auth_bucket(anonymous_client, btc_candle):
    """A locked-out auth bucket must not take the public read API down with it."""
    limiter.reset()
    with patch.object(config, "RATE_LIMIT_AUTH_PER_MINUTE", 1):
        for _ in range(3):
            await anonymous_client.post(
                "/api/v1/auth/jwt/login", data={"username": "a@b.com", "password": "xxxxxxxxxxxx"}
            )
        response = await anonymous_client.get("/api/v1/market/candles/BTC%2FUSD")

    assert response.status_code == 200


async def test_health_and_metrics_are_never_rate_limited(anonymous_client):
    """Prometheus scrapes every 15s and the liveness probe must never get a 429."""
    limiter.reset()
    with patch.object(config, "RATE_LIMIT_READ_PER_MINUTE", 1):
        for _ in range(5):
            assert (await anonymous_client.get("/health")).status_code == 200


async def test_successful_responses_advertise_the_remaining_budget(anonymous_client):
    limiter.reset()
    response = await anonymous_client.get("/health")
    # /health is exempt, so use a counted endpoint instead.
    response = await anonymous_client.get("/api/v1/market/markets")
    assert "X-RateLimit-Limit" in response.headers
    assert int(response.headers["X-RateLimit-Remaining"]) >= 0


# ── Bounded inputs ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("limit", [0, -1, 100_000_000])
async def test_candles_rejects_an_out_of_range_limit(anonymous_client, limit):
    """`limit` was a bare int, so one request could ask for the whole table."""
    response = await anonymous_client.get(
        "/api/v1/market/candles/BTC%2FUSD", params={"limit": limit}
    )
    assert response.status_code == 422


async def test_candles_rejects_an_unsupported_interval(anonymous_client, btc_candle):
    """An unknown interval used to return an empty result as a confusing 404."""
    response = await anonymous_client.get(
        "/api/v1/market/candles/BTC%2FUSD", params={"interval": "7m"}
    )
    assert response.status_code == 422


async def test_candles_supports_offset_paging(anonymous_client, multi_candles):
    first = await anonymous_client.get(
        "/api/v1/market/candles/BTC%2FUSD", params={"limit": 1, "offset": 0}
    )
    second = await anonymous_client.get(
        "/api/v1/market/candles/BTC%2FUSD", params={"limit": 1, "offset": 1}
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["data"][0]["id"] != second.json()["data"][0]["id"]


async def test_the_not_found_message_is_in_english(anonymous_client):
    """This message was in Polish — the only non-English string in the API."""
    response = await anonymous_client.get("/api/v1/market/candles/BTC%2FUSD")
    assert response.status_code == 404
    assert "No candles found" in response.json()["detail"]


async def test_exchange_symbols_listing_is_paginated(anonymous_client, exchange):
    response = await anonymous_client.get(
        f"/api/v1/exchanges/{exchange.id}/symbols", params={"limit": 100_000}
    )
    assert response.status_code == 422


# ── Exchange name validation ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "name, reason",
    [
        ("not_a_real_exchange", "unknown to ccxt"),
        ("bin'ance", "a quote would break out of the Flink SQL literal"),
        ("BINANCE", "upper case"),
        ("a" * 64, "too long"),
        ("x", "too short"),
    ],
)
async def test_creating_an_exchange_rejects_an_unsafe_name(client, name, reason):
    """
    `exchanges.name` becomes a ccxt attribute lookup, a Kafka topic segment and
    part of the Flink job's SQL topic-pattern literal, so it cannot be free text.
    """
    response = await client.post("/api/v1/exchanges", json={"name": name, "method": "multi"})
    assert response.status_code == 422, f"should reject {reason}: {name!r}"


async def test_creating_an_exchange_rejects_an_unknown_method(client):
    response = await client.post(
        "/api/v1/exchanges", json={"name": "binance", "method": "telepathy"}
    )
    assert response.status_code == 422


# ── Security headers ─────────────────────────────────────────────────────────

async def test_responses_carry_security_headers(anonymous_client):
    response = await anonymous_client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


async def test_hsts_is_only_sent_when_the_deployment_is_https(anonymous_client):
    """
    Sending HSTS from a plain-http dev server would pin the browser to an
    HTTPS origin that does not exist.
    """
    response = await anonymous_client.get("/health")
    assert "Strict-Transport-Security" not in response.headers


async def test_a_csrf_rejection_still_carries_cors_headers(anonymous_client):
    """
    CORS must run inside the CSRF check. When it ran outside, the 403 had no
    Access-Control-Allow-Origin, so a cross-origin UI saw an opaque network
    error instead of the actual reason it was refused.
    """
    origin = config.CORS_ALLOW_ORIGINS[0]
    anonymous_client.cookies.set(config.AUTH_COOKIE_NAME, "not-a-real-token")

    response = await anonymous_client.post(
        "/api/v1/exchanges",
        json={"name": "binance", "method": "multi"},
        headers={"Origin": origin},          # deliberately no X-Requested-With
    )

    assert response.status_code == 403
    assert response.headers.get("access-control-allow-origin") == origin
