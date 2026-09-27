"""
The in-process rate limiter.

There was no rate limiting at all before this, on any endpoint — including
login, registration and password reset, which is the entire brute-force
defence on an account that can reconfigure exchanges and insert prices.
"""

from unittest.mock import MagicMock, patch

import pytest

from app import config
from app.middleware.rate_limit import Bucket, SlidingWindowLimiter, bucket_for, client_key


@pytest.fixture
def limiter():
    return SlidingWindowLimiter(window_seconds=60.0)


# ── Window behaviour ─────────────────────────────────────────────────────────

def test_requests_are_allowed_up_to_the_limit_then_refused(limiter):
    bucket = Bucket("auth", 3)
    results = [limiter.check("1.2.3.4", bucket, now=100.0)[0] for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_clients_are_counted_separately(limiter):
    bucket = Bucket("auth", 1)
    assert limiter.check("1.2.3.4", bucket, now=100.0)[0] is True
    assert limiter.check("1.2.3.4", bucket, now=100.0)[0] is False
    assert limiter.check("5.6.7.8", bucket, now=100.0)[0] is True


def test_buckets_are_counted_separately(limiter):
    auth, read = Bucket("auth", 1), Bucket("read", 1)
    assert limiter.check("1.2.3.4", auth, now=100.0)[0] is True
    assert limiter.check("1.2.3.4", auth, now=100.0)[0] is False
    # Exhausting the strict auth bucket must not lock the client out of reads.
    assert limiter.check("1.2.3.4", read, now=100.0)[0] is True


def test_the_window_slides(limiter):
    bucket = Bucket("auth", 2)
    assert limiter.check("1.2.3.4", bucket, now=100.0)[0] is True
    assert limiter.check("1.2.3.4", bucket, now=100.0)[0] is True
    assert limiter.check("1.2.3.4", bucket, now=100.0)[0] is False
    assert limiter.check("1.2.3.4", bucket, now=161.0)[0] is True    # 60s later


def test_a_refused_attempt_is_not_recorded(limiter):
    """
    Otherwise a client hammering the endpoint keeps pushing its own window
    forward and can never get back in, long after it stopped.
    """
    bucket = Bucket("auth", 1)
    limiter.check("1.2.3.4", bucket, now=100.0)
    for _ in range(50):
        limiter.check("1.2.3.4", bucket, now=120.0)      # all refused

    assert limiter.check("1.2.3.4", bucket, now=161.0)[0] is True


def test_retry_after_is_a_positive_number_of_seconds(limiter):
    bucket = Bucket("auth", 1)
    limiter.check("1.2.3.4", bucket, now=100.0)
    allowed, retry_after = limiter.check("1.2.3.4", bucket, now=130.0)
    assert allowed is False
    assert 0 < retry_after <= 61


def test_a_zero_limit_disables_the_bucket(limiter):
    assert all(limiter.check("1.2.3.4", Bucket("read", 0), now=100.0)[0] for _ in range(100))


def test_expired_windows_are_pruned(limiter):
    bucket = Bucket("read", 5)
    for i in range(50):
        limiter.check(f"10.0.0.{i}", bucket, now=100.0)
    assert len(limiter._hits) == 50

    limiter.prune(now=100.0 + 120)
    assert limiter._hits == {}


# ── Bucket routing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "method, path, expected",
    [
        ("POST", "/api/v1/auth/cookie/login", "auth"),
        ("POST", "/api/v1/auth/jwt/login", "auth"),
        ("POST", "/api/v1/auth/register", "auth"),
        ("POST", "/api/v1/auth/forgot-password", "auth"),
        ("PATCH", "/api/v1/users/me", "auth"),
        ("POST", "/api/v1/history/archive/2026-06-23", "archive"),
        ("POST", "/api/v1/exchanges", "write"),
        ("PUT", "/api/v1/exchanges/1/toggle", "write"),
        ("GET", "/api/v1/market/candles/BTCUSD", "read"),
        ("GET", "/api/v1/auth/whatever", "read"),
    ],
)
def test_requests_land_in_the_right_bucket(method, path, expected):
    assert bucket_for(method, path) == expected


# ── Client identification ────────────────────────────────────────────────────

def _request(peer="10.0.0.1", forwarded=None):
    request = MagicMock()
    request.client = MagicMock(host=peer)
    request.headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return request


def test_the_forwarded_header_is_ignored_unless_a_proxy_is_trusted():
    """
    Trusting X-Forwarded-For unconditionally lets any client send a fresh value
    per request and never hit a per-IP limit at all.
    """
    with patch.object(config, "TRUST_PROXY_HEADERS", False):
        assert client_key(_request(peer="10.0.0.1", forwarded="1.2.3.4")) == "10.0.0.1"


def test_the_forwarded_header_is_used_when_a_proxy_is_trusted():
    with patch.object(config, "TRUST_PROXY_HEADERS", True):
        assert client_key(_request(peer="10.0.0.1", forwarded="1.2.3.4")) == "1.2.3.4"


def test_the_left_most_forwarded_address_wins():
    with patch.object(config, "TRUST_PROXY_HEADERS", True):
        key = client_key(_request(forwarded="1.2.3.4, 10.0.0.9, 10.0.0.10"))
        assert key == "1.2.3.4"


def test_a_missing_peer_address_still_yields_a_key():
    request = MagicMock()
    request.client = None
    request.headers = {}
    with patch.object(config, "TRUST_PROXY_HEADERS", False):
        assert client_key(request) == "unknown"
