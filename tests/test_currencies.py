"""
Display currencies: prices are stored in USD and converted on the way out with
the ECB rate of each candle's own date.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import status

from app.auth.csrf import CSRF_HEADER
from app.models.candle import Candle
from app.models.exchange import Exchange
from app.models.fiat_rate import FiatRate

# 1 USD = 4.00 PLN on Friday 2026-06-19, 3.50 PLN on Monday 2026-06-22.
FRIDAY, MONDAY = date(2026, 6, 19), date(2026, 6, 22)


@pytest_asyncio.fixture
async def pln_rates(db_session):
    db_session.add_all([
        FiatRate(rate_date=FRIDAY, currency="PLN", units_per_usd=Decimal("4.00000000")),
        FiatRate(rate_date=MONDAY, currency="PLN", units_per_usd=Decimal("3.50000000")),
        FiatRate(rate_date=MONDAY, currency="EUR", units_per_usd=Decimal("0.90000000")),
    ])
    await db_session.commit()


async def _candle(db_session, when: datetime, close: float = 100.0):
    db_session.add(Candle(
        exchange="binance", ticker="BTC/USD", source_ticker="BTC/USDT", quote_currency="USD", fx_rate=1,
        interval="1m", timestamp=when,
        open_price=close, high_price=close, low_price=close, close_price=close, volume=2,
    ))
    await db_session.commit()


# ── GET /currencies ──────────────────────────────────────────────────────────

async def test_currencies_lists_usd_and_every_currency_with_a_rate(client, pln_rates):
    response = await client.get("/api/v1/currencies")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["default"] == "USD"
    by_code = {c["code"]: c for c in data["currencies"]}
    assert set(by_code) == {"USD", "EUR", "PLN"}
    assert by_code["PLN"]["units_per_usd"] == "3.50000000"      # the newest rate
    assert by_code["PLN"]["rate_date"] == "2026-06-22"
    assert by_code["PLN"]["name"] == "Polish złoty"


async def test_currencies_is_public_and_offers_usd_before_any_rate_is_loaded(anonymous_client):
    response = await anonymous_client.get("/api/v1/currencies")

    assert response.status_code == status.HTTP_200_OK
    assert [c["code"] for c in response.json()["data"]["currencies"]] == ["USD"]


# ── ?currency= on candles ────────────────────────────────────────────────────

async def test_candles_convert_with_the_rate_of_the_candles_own_date(client, db_session, pln_rates):
    await _candle(db_session, datetime(2026, 6, 22, 12, 0), close=100.0)

    response = await client.get("/api/v1/market/candles/BTC%2FUSD", params={"currency": "pln"})

    assert response.status_code == status.HTTP_200_OK
    candle = response.json()["data"][0]
    assert candle["close_price"] == "350.00000000"
    assert candle["quote_currency"] == "PLN"
    assert candle["currency_rate"] == "3.50000000"
    assert candle["rate_date"] == "2026-06-22"
    assert candle["volume"] == "2.00000000"          # base units — never converted
    assert candle["ticker"] == "BTC/USD"             # the market key stays the same


async def test_a_weekend_candle_uses_fridays_rate(client, db_session, pln_rates):
    await _candle(db_session, datetime(2026, 6, 20, 12, 0), close=100.0)   # Saturday

    response = await client.get("/api/v1/market/candles/BTC%2FUSD", params={"currency": "PLN"})

    candle = response.json()["data"][0]
    assert candle["close_price"] == "400.00000000"
    assert candle["rate_date"] == "2026-06-19"


async def test_candles_without_currency_are_unchanged_usd(client, btc_candle, pln_rates):
    response = await client.get("/api/v1/market/candles/BTC%2FUSD")

    candle = response.json()["data"][0]
    assert candle["close_price"] == "65200.00000000"
    assert candle["quote_currency"] == "USD"
    assert candle["currency_rate"] is None


async def test_unsupported_currency_is_a_422(client, btc_candle):
    response = await client.get("/api/v1/market/candles/BTC%2FUSD", params={"currency": "XYZ"})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_a_currency_without_any_rate_yet_is_a_503(client, btc_candle):
    response = await client.get("/api/v1/market/candles/BTC%2FUSD", params={"currency": "NOK"})

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


async def test_history_converts_too(client, history_candles, pln_rates):
    response = await client.get(
        "/api/v1/history/BTC%2FUSD",
        params={"date_from": "2026-06-22", "date_to": "2026-06-23", "currency": "PLN"},
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    # 2026-06-22 and 2026-06-23 both use Monday's 3.50 (nothing newer is stored)
    assert [c["close_price"] for c in data] == ["228200.00000000", "228550.00000000"]
    assert {c["quote_currency"] for c in data} == {"PLN"}


# ── Stocks: market list and the poll source ──────────────────────────────────

async def test_markets_report_their_asset_class(client, db_session):
    from app.models.exchange import Symbol

    yahoo = Exchange(name="yahoo", method="poll", asset_class="stock")
    binance = Exchange(name="binance", method="multi")
    db_session.add_all([yahoo, binance])
    await db_session.flush()
    db_session.add_all([
        Symbol(exchange_id=yahoo.id, ticker="PKN.WA/PLN", interval="1m"),
        Symbol(exchange_id=binance.id, ticker="BTC/USDT", interval="1m"),
    ])
    await db_session.commit()

    response = await client.get("/api/v1/market/markets")

    by_ticker = {m["ticker"]: m for m in response.json()["data"]}
    assert by_ticker["PKN.WA/USD"]["asset_class"] == "stock"
    assert by_ticker["BTC/USD"]["asset_class"] == "crypto"


async def test_create_yahoo_exchange_marks_it_as_stocks(client):
    response = await client.post("/api/v1/exchanges", json={"name": "yahoo", "method": "poll"})

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["data"]["asset_class"] == "stock"


async def test_a_polled_exchange_cannot_take_30s(client, db_session):
    yahoo = Exchange(name="yahoo", method="poll", asset_class="stock")
    db_session.add(yahoo)
    await db_session.commit()

    single = await client.post(f"/api/v1/exchanges/{yahoo.id}/symbols", json={"ticker": "AAPL/USD", "interval": "30s"})
    bulk = await client.post(
        f"/api/v1/exchanges/{yahoo.id}/symbols/bulk",
        json={"tickers": ["PKN.WA/PLN"], "intervals": ["30s", "1m"]},
    )

    assert single.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    result = bulk.json()["data"]
    assert [(s["ticker"], s["interval"]) for s in result["created"]] == [("PKN.WA/PLN", "1m")]
    assert [s["interval"] for s in result["skipped"]] == ["30s"]


# ── Users: preferred currency ────────────────────────────────────────────────

async def test_a_user_can_save_a_preferred_currency(anonymous_client):
    credentials = {"email": "pl-user@example.com", "password": "supersecret123"}
    assert (await anonymous_client.post("/api/v1/auth/register", json=credentials)).status_code == 201
    await anonymous_client.post(
        "/api/v1/auth/cookie/login",
        data={"username": credentials["email"], "password": credentials["password"]},
    )
    csrf = {CSRF_HEADER: "tradingmaster-ui"}

    assert (await anonymous_client.get("/api/v1/users/me")).json()["preferred_currency"] is None
    saved = await anonymous_client.patch("/api/v1/users/me", json={"preferred_currency": "pln"}, headers=csrf)
    rejected = await anonymous_client.patch("/api/v1/users/me", json={"preferred_currency": "XYZ"}, headers=csrf)

    assert saved.status_code == status.HTTP_200_OK
    assert saved.json()["preferred_currency"] == "PLN"
    assert rejected.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


# ── WebSocket pump ───────────────────────────────────────────────────────────

async def test_the_pump_converts_live_candles_and_skips_ones_without_a_rate(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.fiat.rates import FiatRateCache
    from app.kafka.stream_hub import Subscription
    from app.routers import market

    cache = FiatRateCache()
    cache.load([("PLN", MONDAY, Decimal("3.5"))])
    monkeypatch.setattr(market, "fiat_rates", cache)

    shared = {"interval": "1m", "timestamp": "2026-06-22T12:00:00", "close_price": "100.00000000",
              "open_price": "100.00000000", "high_price": "100.00000000", "low_price": "100.00000000",
              "volume": "1.00000000", "quote_currency": "USD"}
    subscription = Subscription(("t",), maxsize=10)
    subscription.offer({**shared, "timestamp": "2026-06-01T12:00:00"})   # before any stored rate
    subscription.offer(shared)

    sent = []

    async def send_json(payload):
        sent.append(payload)
        raise asyncio.CancelledError

    websocket = MagicMock()
    websocket.send_json = AsyncMock(side_effect=send_json)

    with pytest.raises(asyncio.CancelledError):
        await market._pump(websocket, subscription, wanted_interval=None, currency="PLN")

    assert len(sent) == 1
    assert sent[0]["close_price"] == "350.00000000"
    assert sent[0]["quote_currency"] == "PLN"
    assert sent[0]["rate_date"] == "2026-06-22"
    assert shared["close_price"] == "100.00000000"     # the shared payload is untouched
