"""Real wallet/trade persistence with deterministic public quote boundaries."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
import uuid

import pytest
from sqlalchemy import func, select

from app import config
from app.auth import current_active_user
from app.helpers.time import utc_now_naive
from app.models.exchange import Exchange, Symbol
from app.models.fiat_rate import FiatRate
from app.models.trading import CreditEntry, Trade, TradingQuote, Wallet
from app.models.user import User
from app.trading.quotes import PriceQuote, QuoteService, QuoteUnavailable, quote_service

PREFIX = "/api/v1/trading"


def key():
    return {"Idempotency-Key": str(uuid.uuid4())}


@pytest.fixture
def enable_trading(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "development")
    monkeypatch.setattr(config, "DEV_TRADING_ENABLED", True)
    monkeypatch.setattr(config, "DEV_INITIAL_CREDITS", Decimal("1000"))


@pytest.fixture
def price(monkeypatch):
    async def fetch(db, source, **kwargs):
        now = utc_now_naive()
        return PriceQuote(Decimal("99"), Decimal("100"), now, now), Decimal(1)
    mock = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(quote_service, "get", mock)
    return mock


@pytest.fixture
async def trader(client, db_session, enable_trading, price):
    from app.main import app
    user = User(id=uuid.uuid4(), email="paper@example.com", hashed_password="unused", is_active=True,
                is_superuser=False, is_verified=False)
    exchange = Exchange(name="kraken", method="ohlcv")
    db_session.add_all([user, exchange])
    await db_session.flush()
    db_session.add(Symbol(exchange_id=exchange.id, ticker="BTC/USD", interval="1m"))
    await db_session.commit()
    app.dependency_overrides[current_active_user] = lambda: user
    await client.post(PREFIX + "/wallet/initialize")
    return client


async def buy_quote(client, budget="100"):
    result = await client.post(PREFIX + "/quotes", json={"side": "buy", "exchange": "kraken",
                                                       "ticker": "BTC/USD", "budget": budget})
    assert result.status_code == 200, result.text
    return result.json()["data"]


async def purchase(client, budget="100"):
    quote = await buy_quote(client, budget)
    result = await client.post(PREFIX + "/trades", json={"quote_id": quote["id"]}, headers=key())
    assert result.status_code == 200, result.text
    return result.json()["data"]


async def test_initial_funds_apply_once_and_topups_are_idempotent(trader, monkeypatch, db_session):
    monkeypatch.setattr(config, "DEV_INITIAL_CREDITS", Decimal("8000"))
    result = await trader.post(PREFIX + "/wallet/initialize")
    assert result.json()["data"]["balance"] == "1000.00000000"
    headers = key()
    first = await trader.post(PREFIX + "/wallet/demo-top-ups", json={"amount": "12.25"}, headers=headers)
    second = await trader.post(PREFIX + "/wallet/demo-top-ups", json={"amount": "12.250"}, headers=headers)
    assert first.json() == second.json()
    assert first.json()["data"]["balance"] == "1012.25000000"
    conflict = await trader.post(PREFIX + "/wallet/demo-top-ups", json={"amount": "13"}, headers=headers)
    assert conflict.status_code == 409
    assert await db_session.scalar(select(func.count()).select_from(CreditEntry)) == 2


async def test_buy_spread_loss_full_sale_and_closed_history(trader, db_session):
    bought = await purchase(trader)
    assert bought["wallet"]["balance"] == "900.00000000"
    assert bought["trade"]["quantity"] == "1.00000000"
    result = (await trader.get(PREFIX + "/trades")).json()["data"]["items"][0]
    assert result["valuation"]["sell_value"] == "99.00000000"
    assert result["valuation"]["unrealized_pnl"] == "-1.00000000"
    assert result["valuation"]["spread"] == "1.00000000"
    trade_id = bought["trade"]["id"]
    quote = (await trader.post(PREFIX + "/quotes", json={"side": "sell", "trade_id": trade_id})).json()["data"]
    headers = key()
    sale = await trader.post(PREFIX + f"/trades/{trade_id}/sell", json={"quote_id": quote["id"]}, headers=headers)
    assert sale.status_code == 200
    assert sale.json()["data"]["wallet"]["balance"] == "999.00000000"
    assert sale.json()["data"]["trade"]["realized_pnl"] == "-1.00000000"
    replay = await trader.post(PREFIX + f"/trades/{trade_id}/sell", json={"quote_id": quote["id"]}, headers=headers)
    assert replay.json() == sale.json()
    duplicate = await trader.post(PREFIX + f"/trades/{trade_id}/sell", json={"quote_id": quote["id"]}, headers=key())
    assert duplicate.status_code == 409
    assert (await trader.get(PREFIX + "/trades")).json()["data"]["total"] == 0
    assert (await trader.get(PREFIX + "/trades?status=closed")).json()["data"]["total"] == 1
    entries = (await db_session.scalars(select(CreditEntry))).all()
    assert sum(entry.amount for entry in entries) == Decimal("999")


async def test_purchase_retry_replays_and_other_key_cannot_reuse_quote(trader):
    quote = await buy_quote(trader)
    headers = key()
    first = await trader.post(PREFIX + "/trades", json={"quote_id": quote["id"]}, headers=headers)
    second = await trader.post(PREFIX + "/trades", json={"quote_id": quote["id"]}, headers=headers)
    assert first.json() == second.json()
    assert (await trader.post(PREFIX + "/trades", json={"quote_id": quote["id"]}, headers=key())).status_code == 409
    other = await buy_quote(trader)
    assert (await trader.post(PREFIX + "/trades", json={"quote_id": other["id"]}, headers=headers)).status_code == 409


async def test_insufficient_credits_and_expired_quote_do_not_change_wallet(trader, db_session):
    quote = await buy_quote(trader, "1001")
    assert (await trader.post(PREFIX + "/trades", json={"quote_id": quote["id"]}, headers=key())).status_code == 409
    stored = await db_session.get(TradingQuote, quote["id"])
    stored.expires_at = utc_now_naive() - timedelta(seconds=1)
    await db_session.commit()
    expired = await trader.post(PREFIX + "/trades", json={"quote_id": quote["id"]}, headers=key())
    assert expired.status_code == 409
    assert "expired" in expired.json()["detail"]
    assert (await trader.get(PREFIX + "/wallet")).json()["data"]["balance"] == "1000.00000000"
    assert await db_session.scalar(select(func.count()).select_from(Trade)) == 0


async def test_rounding_preserves_unspent_credits(trader, price):
    async def thirds(db, source, **kwargs):
        now = utc_now_naive()
        return PriceQuote(Decimal("2.99"), Decimal(3), now, now), Decimal(1)
    price.side_effect = thirds
    result = await purchase(trader, "1")
    assert result["trade"]["quantity"] == "0.33333333"
    assert result["trade"]["cost"] == "0.99999999"
    assert result["wallet"]["balance"] == "999.00000001"


@pytest.mark.parametrize("bid, expected", [("110", "10.00000000"), ("90", "-10.00000000")])
async def test_profitable_and_losing_sales(trader, price, bid, expected):
    result = await purchase(trader)
    async def moved(db, source, **kwargs):
        now = utc_now_naive()
        return PriceQuote(Decimal(bid), Decimal(bid) + 1, now, now), Decimal(1)
    price.side_effect = moved
    trade_id = result["trade"]["id"]
    quote = (await trader.post(PREFIX + "/quotes", json={"side": "sell", "trade_id": trade_id})).json()["data"]
    sale = await trader.post(PREFIX + f"/trades/{trade_id}/sell", json={"quote_id": quote["id"]}, headers=key())
    assert sale.json()["data"]["trade"]["realized_pnl"] == expected


async def test_disabled_market_cannot_execute_existing_preview(trader, db_session):
    quote = await buy_quote(trader)
    exchange = await db_session.scalar(select(Exchange).where(Exchange.name == "kraken"))
    exchange.enabled = False
    await db_session.commit()
    result = await trader.post(PREFIX + "/trades", json={"quote_id": quote["id"]}, headers=key())
    assert result.status_code == 409


async def test_quote_outage_reports_unknown_valuation_and_blocks_new_previews(trader, price):
    await purchase(trader)
    price.side_effect = QuoteUnavailable("Provider quote is stale")
    listing = (await trader.get(PREFIX + "/trades")).json()["data"]["items"][0]
    assert listing["valuation"] is None
    assert "stale" in listing["valuation_error"]
    result = await trader.post(PREFIX + "/quotes", json={"side": "buy", "exchange": "kraken", "ticker": "BTC/USD", "budget": "100"})
    assert result.status_code == 503


async def test_user_cannot_access_another_wallet_trade_or_quote(trader, db_session):
    from app.main import app
    bought = await purchase(trader)
    quote = await buy_quote(trader)
    other = User(id=uuid.uuid4(), email="other@example.com", hashed_password="unused", is_active=True)
    db_session.add(other)
    await db_session.commit()
    app.dependency_overrides[current_active_user] = lambda: other
    assert (await trader.get(PREFIX + "/wallet")).status_code == 404
    await trader.post(PREFIX + "/wallet/initialize")
    assert (await trader.get(PREFIX + "/trades")).json()["data"]["total"] == 0
    assert (await trader.post(PREFIX + "/trades", json={"quote_id": quote["id"]}, headers=key())).status_code == 404
    result = await trader.post(PREFIX + "/quotes", json={"side": "sell", "trade_id": bought["trade"]["id"]})
    assert result.status_code == 404


async def test_concurrent_purchases_cannot_overspend(trader):
    first, second = await buy_quote(trader, "700"), await buy_quote(trader, "700")
    results = await asyncio.gather(*[
        trader.post(PREFIX + "/trades", json={"quote_id": quote["id"]}, headers=key())
        for quote in (first, second)
    ])
    assert sorted(result.status_code for result in results) == [200, 409]
    assert (await trader.get(PREFIX + "/wallet")).json()["data"]["balance"] == "300.00000000"


async def test_concurrent_sales_credit_only_once(trader):
    trade_id = (await purchase(trader))["trade"]["id"]
    quotes = [(await trader.post(PREFIX + "/quotes", json={"side": "sell", "trade_id": trade_id})).json()["data"] for _ in range(2)]
    results = await asyncio.gather(*[
        trader.post(PREFIX + f"/trades/{trade_id}/sell", json={"quote_id": quote["id"]}, headers=key())
        for quote in quotes
    ])
    assert sorted(result.status_code for result in results) == [200, 409]
    assert (await trader.get(PREFIX + "/wallet")).json()["data"]["balance"] == "999.00000000"


async def test_ledger_failure_rolls_back_execution(trader, db_session, monkeypatch):
    from app.trading import service
    quote = await buy_quote(trader)
    def failed_entry(**kwargs):
        raise RuntimeError("simulated ledger failure")
    monkeypatch.setattr(service, "CreditEntry", failed_entry)
    # replay needs the ORM class; fail only after a successful lookup instead.
    monkeypatch.setattr(service, "replay", AsyncMock(return_value=None))
    with pytest.raises(RuntimeError, match="ledger failure"):
        await trader.post(PREFIX + "/trades", json={"quote_id": quote["id"]}, headers=key())
    assert (await trader.get(PREFIX + "/wallet")).json()["data"]["balance"] == "1000.00000000"
    assert await db_session.scalar(select(func.count()).select_from(Trade)) == 0


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "0.000000001", "1000000000001"])
async def test_invalid_topup_amounts(trader, amount):
    result = await trader.post(PREFIX + "/wallet/demo-top-ups", json={"amount": amount}, headers=key())
    assert result.status_code == 422


async def test_missing_idempotency_key_and_injected_price_rejected(trader):
    assert (await trader.post(PREFIX + "/wallet/demo-top-ups", json={"amount": "1"})).status_code == 422
    quote = await buy_quote(trader)
    result = await trader.post(PREFIX + "/trades", json={"quote_id": quote["id"], "ask": "0.01"}, headers=key())
    assert result.status_code == 422


async def test_stock_purchase_uses_yahoo_bidask_and_real_fiat_conversion(trader, db_session, monkeypatch):
    from app.trading import quotes
    yahoo = Exchange(name="yahoo", method="poll", asset_class="stock")
    db_session.add(yahoo)
    await db_session.flush()
    db_session.add_all([
        Symbol(exchange_id=yahoo.id, ticker="PKN.WA/PLN", interval="1m"),
        FiatRate(currency="PLN", rate_date=utc_now_naive().date(), units_per_usd=Decimal(4)),
    ])
    await db_session.commit()
    def native(source):
        now = utc_now_naive()
        return PriceQuote(Decimal(396), Decimal(400), now - timedelta(minutes=15), now,
                          delayed=True, session_end=now + timedelta(hours=1))
    monkeypatch.setattr(quotes, "fetch_stock", native)
    monkeypatch.setattr(quote_service, "get", QuoteService().get)
    preview = await trader.post(PREFIX + "/quotes", json={"side": "buy", "exchange": "yahoo", "ticker": "PKN.WA/USD", "budget": "100"})
    assert preview.status_code == 200, preview.text
    quote = preview.json()["data"]
    assert quote["delayed"] is True
    assert quote["fx_rate"] == "0.25000000"
    assert quote["ask"] == "100.00000000" and quote["bid"] == "99.00000000"
    bought = await trader.post(PREFIX + "/trades", json={"quote_id": quote["id"]}, headers=key())
    assert bought.status_code == 200
    assert bought.json()["data"]["trade"]["source_ticker"] == "PKN.WA/PLN"
    listing = (await trader.get(PREFIX + "/trades")).json()["data"]["items"][0]
    assert listing["valuation"]["unrealized_pnl"] == "-1.00000000"


@pytest.mark.parametrize("days_old", [None, 8])
async def test_missing_or_stale_fiat_prevents_execution(trader, db_session, monkeypatch, days_old):
    from app.trading import quotes
    yahoo = Exchange(name="yahoo", method="poll", asset_class="stock")
    db_session.add(yahoo)
    await db_session.flush()
    db_session.add(Symbol(exchange_id=yahoo.id, ticker="PKN.WA/PLN", interval="1m"))
    if days_old is not None:
        db_session.add(FiatRate(currency="PLN", rate_date=utc_now_naive().date() - timedelta(days=days_old), units_per_usd=4))
    await db_session.commit()
    def native(source):
        now = utc_now_naive()
        return PriceQuote(Decimal(396), Decimal(400), now, now, True, now + timedelta(hours=1))
    monkeypatch.setattr(quotes, "fetch_stock", native)
    monkeypatch.setattr(quote_service, "get", QuoteService().get)
    preview = await trader.post(PREFIX + "/quotes", json={"side": "buy", "exchange": "yahoo", "ticker": "PKN.WA/USD", "budget": "100"})
    assert preview.status_code == 503
    assert "conversion" in preview.json()["detail"]


async def test_budget_that_rounds_to_zero_quantity_is_rejected(trader, price):
    async def expensive(db, source, **kwargs):
        now = utc_now_naive()
        return PriceQuote(Decimal(99999), Decimal(100000), now, now), Decimal(1)
    price.side_effect = expensive
    result = await trader.post(PREFIX + "/quotes", json={"side": "buy", "exchange": "kraken", "ticker": "BTC/USD", "budget": "0.00000001"})
    assert result.status_code == 422


async def test_concurrent_wallet_initialization_seeds_once(trader, db_session):
    from app.main import app
    user = User(id=uuid.uuid4(), email="new-wallet@example.com", hashed_password="unused", is_active=True)
    db_session.add(user)
    await db_session.commit()
    app.dependency_overrides[current_active_user] = lambda: user
    results = await asyncio.gather(trader.post(PREFIX + "/wallet/initialize"), trader.post(PREFIX + "/wallet/initialize"))
    assert all(result.status_code == 200 for result in results)
    assert all(result.json()["data"]["balance"] == "1000.00000000" for result in results)
    assert await db_session.scalar(select(func.count()).select_from(CreditEntry).where(CreditEntry.user_id == user.id)) == 1


async def test_auth_csrf_and_development_gate(anonymous_client, enable_trading, monkeypatch):
    assert (await anonymous_client.get(PREFIX + "/wallet")).status_code == 401
    assert (await anonymous_client.get(PREFIX + "/trades")).status_code == 401
    assert (await anonymous_client.post(PREFIX + "/wallet/initialize")).status_code == 401
    anonymous_client.cookies.set(config.AUTH_COOKIE_NAME, "invalid")
    assert (await anonymous_client.post(PREFIX + "/wallet/initialize")).status_code == 403
    anonymous_client.cookies.clear()
    monkeypatch.setattr(config, "APP_ENV", "production")
    assert (await anonymous_client.get(PREFIX + "/capabilities")).json()["data"]["enabled"] is False
    assert (await anonymous_client.post(PREFIX + "/wallet/initialize")).status_code == 404
