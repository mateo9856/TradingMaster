from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import config
from app.models.user import User
from app.trading.guest import seed_guest


@pytest.fixture
def guest_settings(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "development")
    monkeypatch.setattr(config, "DEV_TRADING_ENABLED", True)
    monkeypatch.setattr(config, "DEV_GUEST_ENABLED", True)
    monkeypatch.setattr(config, "DEV_GUEST_EMAIL", "demo@example.com")
    monkeypatch.setattr(config, "DEV_GUEST_PASSWORD", "correct-horse-battery-staple")


async def test_guest_provisioning_login_and_no_password_reset(anonymous_client, db_session, guest_settings, monkeypatch):
    await seed_guest(db_session)
    user = await db_session.scalar(select(User))
    original_hash = user.hashed_password
    monkeypatch.setattr(config, "DEV_GUEST_PASSWORD", "another-valid-password")
    await seed_guest(db_session)
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
    await db_session.refresh(user)
    assert user.is_dev_guest and user.hashed_password == original_hash
    login = await anonymous_client.post("/api/v1/auth/jwt/login", data={"username": "demo@example.com", "password": "correct-horse-battery-staple"})
    assert login.status_code == 200
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    result = await anonymous_client.post("/api/v1/trading/wallet/initialize", headers=headers)
    assert result.status_code == 200
    assert Decimal(result.json()["data"]["balance"]) == config.TRADING_INITIAL_CREDITS


@pytest.mark.parametrize("email", ["demo@example.com", "DEMO@example.com"])
async def test_guest_email_collision_is_not_overwritten(db_session, guest_settings, email):
    db_session.add(User(email=email, hashed_password="existing", is_active=True))
    await db_session.commit()
    with pytest.raises(RuntimeError, match="existing account"):
        await seed_guest(db_session)
    assert (await db_session.scalar(select(User))).hashed_password == "existing"


async def test_guest_seeding_disabled_outside_development(db_session, guest_settings, monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "production")
    await seed_guest(db_session)
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


def test_trading_configuration_rejects_non_development(guest_settings, monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "staging")
    with pytest.raises(config.ConfigError, match="APP_ENV=development"):
        config.validate_config()


@pytest.mark.parametrize("amount", [Decimal("NaN"), Decimal("Infinity"), Decimal("-1"), Decimal("1e20"), Decimal("0.000000001")])
def test_initial_funds_config_validation(guest_settings, monkeypatch, amount):
    monkeypatch.setattr(config, "DEV_INITIAL_CREDITS", amount)
    with pytest.raises(config.ConfigError, match="DEV_INITIAL_CREDITS"):
        config.validate_config()
