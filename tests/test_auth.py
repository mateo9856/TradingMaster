import pytest

async def test_protected_endpoint_rejects_anonymous_request(anonymous_client):
    response = await anonymous_client.post(
        "/api/v1/exchanges", json={"name": "coinbase", "method": "trades"}
    )

    assert response.status_code == 401


async def test_register_login_and_access_protected_endpoint(anonymous_client):
    register = await anonymous_client.post(
        "/api/v1/auth/register",
        json={"email": "trader@example.com", "password": "supersecret123"},
    )
    assert register.status_code == 201

    login = await anonymous_client.post(
        "/api/v1/auth/jwt/login",
        data={"username": "trader@example.com", "password": "supersecret123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    response = await anonymous_client.post(
        "/api/v1/exchanges",
        json={"name": "coinbase", "method": "trades"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201


async def test_login_with_wrong_password_is_rejected(anonymous_client):
    await anonymous_client.post(
        "/api/v1/auth/register",
        json={"email": "trader2@example.com", "password": "supersecret123"},
    )

    login = await anonymous_client.post(
        "/api/v1/auth/jwt/login",
        data={"username": "trader2@example.com", "password": "wrong-password"},
    )

    assert login.status_code == 400


# ── Password policy ──────────────────────────────────────────────────────────
# fastapi-users' default validate_password is a no-op, so before app/auth/
# manager.py overrode it, "a" was an accepted password for an account that can
# pause exchanges and insert prices.

@pytest.mark.parametrize(
    "password, reason",
    [
        ("short", "too short"),
        ("a" * 11, "one below the minimum"),
        ("password1234", "a common password"),
        ("a" * 16, "a single repeated character"),
        ("x" * 200, "too long"),
    ],
)
async def test_registration_rejects_a_weak_password(anonymous_client, password, reason):
    response = await anonymous_client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": password},
    )
    assert response.status_code == 400, f"should reject {reason}: {password!r}"


async def test_registration_rejects_a_password_containing_the_email(anonymous_client):
    response = await anonymous_client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "alice-in-wonderland"},
    )
    assert response.status_code == 400


async def test_registration_accepts_a_strong_password(anonymous_client):
    response = await anonymous_client.post(
        "/api/v1/auth/register",
        json={"email": "strong@example.com", "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 201


async def test_reset_and_verify_tokens_are_signed_with_their_own_keys():
    """
    One shared secret signed session JWTs, password-reset tokens and
    verification tokens, so a leak of any one of them compromised all three.
    """
    from app.auth.manager import UserManager
    from app.config import AUTH_SECRET

    assert UserManager.reset_password_token_secret != AUTH_SECRET
    assert UserManager.verification_token_secret != AUTH_SECRET
    assert UserManager.reset_password_token_secret != UserManager.verification_token_secret
