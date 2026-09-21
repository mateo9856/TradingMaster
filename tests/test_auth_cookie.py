"""
Browser sessions: the JWT travels in an http-only cookie instead of being handed
to page JavaScript, and cookie-authenticated writes must carry the CSRF header.

The bearer backend is exercised here too, because the point of keeping both is
that adding cookies changed nothing for API clients.
"""

import pytest

from app.auth.csrf import CSRF_HEADER
from app.config import AUTH_COOKIE_NAME

CREDENTIALS = {"email": "cookie-user@example.com", "password": "supersecret123"}
CSRF = {CSRF_HEADER: "tradingmaster-ui"}


async def register(client) -> None:
    response = await client.post("/api/v1/auth/register", json=CREDENTIALS)
    assert response.status_code == 201


async def login(client) -> None:
    """Signs in through the cookie backend; the cookie is kept by the client jar."""
    response = await client.post(
        "/api/v1/auth/cookie/login",
        data={"username": CREDENTIALS["email"], "password": CREDENTIALS["password"]},
    )
    assert response.status_code in (200, 204)


def set_cookie_header(response) -> str:
    return response.headers.get("set-cookie", "")


# ── Logging in ───────────────────────────────────────────────────────────────

async def test_cookie_login_sets_an_unreadable_cookie_and_returns_no_token(anonymous_client):
    await register(anonymous_client)

    response = await anonymous_client.post(
        "/api/v1/auth/cookie/login",
        data={"username": CREDENTIALS["email"], "password": CREDENTIALS["password"]},
    )

    header = set_cookie_header(response).lower()
    assert AUTH_COOKIE_NAME in header
    assert "httponly" in header                       # JavaScript cannot read it
    assert "samesite=strict" in header                # never sent cross-site
    assert anonymous_client.cookies.get(AUTH_COOKIE_NAME)
    # Nothing token-shaped is handed to the page.
    assert "access_token" not in response.text


async def test_cookie_login_with_wrong_password_sets_no_cookie(anonymous_client):
    await register(anonymous_client)

    response = await anonymous_client.post(
        "/api/v1/auth/cookie/login",
        data={"username": CREDENTIALS["email"], "password": "wrong-password"},
    )

    assert response.status_code == 400
    assert AUTH_COOKIE_NAME not in set_cookie_header(response)
    assert anonymous_client.cookies.get(AUTH_COOKIE_NAME) is None


async def test_cookie_secure_flag_follows_configuration(anonymous_client, monkeypatch):
    """Production sets AUTH_COOKIE_SECURE=true; the dev default keeps http working."""
    from app.auth import backend

    await register(anonymous_client)
    monkeypatch.setattr(backend.cookie_transport, "cookie_secure", True)

    response = await anonymous_client.post(
        "/api/v1/auth/cookie/login",
        data={"username": CREDENTIALS["email"], "password": CREDENTIALS["password"]},
    )

    assert "secure" in set_cookie_header(response).lower()


# ── Using the session ────────────────────────────────────────────────────────

async def test_cookie_authenticates_a_write_with_the_csrf_header(anonymous_client):
    await register(anonymous_client)
    await login(anonymous_client)

    response = await anonymous_client.post(
        "/api/v1/exchanges",
        json={"name": "coinbase", "method": "trades"},
        headers=CSRF,
    )

    assert response.status_code == 201


async def test_cookie_write_without_the_csrf_header_is_rejected(anonymous_client):
    await register(anonymous_client)
    await login(anonymous_client)

    response = await anonymous_client.post(
        "/api/v1/exchanges", json={"name": "coinbase", "method": "trades"}
    )

    assert response.status_code == 403
    assert CSRF_HEADER in response.json()["detail"]


async def test_cookie_reads_need_no_csrf_header(anonymous_client):
    await register(anonymous_client)
    await login(anonymous_client)

    response = await anonymous_client.get("/api/v1/users/me")

    assert response.status_code == 200
    assert response.json()["email"] == CREDENTIALS["email"]


async def test_profile_update_through_the_cookie_session_is_also_guarded(anonymous_client):
    """FastAPI Users' own routes are covered too — the guard is middleware, not a dependency."""
    await register(anonymous_client)
    await login(anonymous_client)

    unguarded = await anonymous_client.patch("/api/v1/users/me", json={"password": "another-secret-1"})
    guarded = await anonymous_client.patch(
        "/api/v1/users/me", json={"password": "another-secret-1"}, headers=CSRF
    )

    assert unguarded.status_code == 403
    assert guarded.status_code == 200


async def test_logout_clears_the_cookie_and_ends_the_session(anonymous_client):
    await register(anonymous_client)
    await login(anonymous_client)

    logout = await anonymous_client.post("/api/v1/auth/cookie/logout", headers=CSRF)
    after = await anonymous_client.post(
        "/api/v1/exchanges", json={"name": "kraken", "method": "ohlcv"}, headers=CSRF
    )

    assert logout.status_code in (200, 204)
    assert not anonymous_client.cookies.get(AUTH_COOKIE_NAME)
    assert after.status_code == 401


@pytest.mark.parametrize("value", ["not-a-jwt", "eyJhbGciOiJIUzI1NiJ9.tampered.signature"])
async def test_a_forged_cookie_is_unauthorized_not_a_crash(anonymous_client, value):
    anonymous_client.cookies.set(AUTH_COOKIE_NAME, value)

    response = await anonymous_client.post(
        "/api/v1/exchanges",
        json={"name": "coinbase", "method": "trades"},
        headers=CSRF,
    )

    assert response.status_code == 401


# ── The bearer backend is untouched ──────────────────────────────────────────

async def test_bearer_login_still_returns_a_token_and_needs_no_csrf_header(anonymous_client):
    await register(anonymous_client)

    login_response = await anonymous_client.post(
        "/api/v1/auth/jwt/login",
        data={"username": CREDENTIALS["email"], "password": CREDENTIALS["password"]},
    )
    token = login_response.json()["access_token"]

    # No cookie in play, so the CSRF guard doesn't apply — curl keeps working.
    response = await anonymous_client.post(
        "/api/v1/exchanges",
        json={"name": "coinbase", "method": "trades"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login_response.status_code == 200
    assert response.status_code == 201


async def test_anonymous_writes_are_still_unauthorized_not_forbidden(anonymous_client):
    """No cookie, no token: the CSRF guard must not mask the 401."""
    response = await anonymous_client.post(
        "/api/v1/exchanges", json={"name": "coinbase", "method": "trades"}
    )

    assert response.status_code == 401
