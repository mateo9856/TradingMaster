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
