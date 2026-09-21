from datetime import datetime

import pytest
from fastapi import status
from sqlalchemy.exc import IntegrityError

from app.models.candle import Candle
from app.routers.market import _resolve_topics

# ---------------------------------------------------------------------------
# GET /candles/{ticker} — unified feed
# ---------------------------------------------------------------------------

async def test_get_candles_success(client, btc_candle):
    # btc_candle fixture seeds one binance BTC/USD candle (source market BTC/USDT)
    response = await client.get("/api/v1/market/candles/BTC%2FUSD")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["status"] == "success"
    assert len(body["data"]) == 1
    candle = body["data"][0]
    assert candle["ticker"] == "BTC/USD"
    assert candle["source_ticker"] == "BTC/USDT"
    assert candle["quote_currency"] == "USD"
    assert candle["exchange"] == "binance"


async def test_get_candles_prices_use_unified_decimal_format(client, btc_candle):
    response = await client.get("/api/v1/market/candles/BTC%2FUSD")

    candle = response.json()["data"][0]
    assert candle["close_price"] == "65200.00000000"
    assert candle["open_price"] == "65000.00000000"
    assert candle["volume"] == "15.40000000"
    assert candle["fx_rate"] == "1.00000000"


@pytest.mark.parametrize("spelling", ["BTC%2FUSDT", "BTCUSDT", "btc-usdt", "BTC%2FUSDC", "BTCUSD"])
async def test_get_candles_resolves_any_spelling_to_unified_ticker(client, btc_candle, spelling):
    response = await client.get(f"/api/v1/market/candles/{spelling}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["data"][0]["ticker"] == "BTC/USD"


async def test_get_candles_same_coin_from_all_exchanges_in_one_format(client, multi_candles):
    response = await client.get("/api/v1/market/candles/BTC%2FUSD?interval=1m")

    data = response.json()["data"]
    assert {c["exchange"] for c in data} == {"binance", "kraken"}
    assert all(set(c) == set(data[0]) for c in data)
    assert all(c["close_price"].count(".") == 1 and len(c["close_price"].split(".")[1]) == 8 for c in data)


async def test_get_candles_filter_by_exchange(client, multi_candles):
    # multi_candles has BTC/USD from both binance and kraken
    response = await client.get("/api/v1/market/candles/BTC%2FUSD?exchange=binance")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    # Only binance candles returned
    assert body["data"]
    assert all(c["exchange"] == "binance" for c in body["data"])


async def test_get_candles_filter_by_interval(client, multi_candles):
    # multi_candles has BTC/USD in both 1m and 5m intervals
    response = await client.get("/api/v1/market/candles/BTC%2FUSD?interval=5m")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["data"]
    assert all(c["interval"] == "5m" for c in body["data"])


async def test_get_candles_supports_30s_interval(client, db_session):
    db_session.add(Candle(
        exchange="coinbase", ticker="SOL/USD", source_ticker="SOL/USD", quote_currency="USD", fx_rate=1,
        interval="30s", timestamp=datetime(2026, 9, 19, 12, 0, 30),
        open_price=150, high_price=151, low_price=149, close_price=150.5, volume=12,
    ))
    await db_session.commit()

    response = await client.get("/api/v1/market/candles/SOL-USD?interval=30s")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["data"][0]["timestamp"] == "2026-09-19T12:00:30"


async def test_get_candles_not_found(client):
    response = await client.get("/api/v1/market/candles/DOGE%2FUSD")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "DOGE/USD" in response.json()["detail"]


@pytest.mark.parametrize("ticker", ["INVALID", "ETH%2FBTC", "BTC%2FEUR"])
async def test_get_candles_unsupported_market_returns_422(client, ticker):
    response = await client.get(f"/api/v1/market/candles/{ticker}")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "Unsupported quote currency" in response.json()["detail"]


async def test_get_candles_wrong_interval_returns_404(client, btc_candle):
    # btc_candle is 1m — querying 1h should return 404
    response = await client.get("/api/v1/market/candles/BTC%2FUSD?interval=1h")

    assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# candles unique key includes interval
# ---------------------------------------------------------------------------

def _candle(interval: str, close: float = 1.0) -> Candle:
    return Candle(
        exchange="binance", ticker="BTC/USD", interval=interval,
        timestamp=datetime(2026, 9, 19, 12, 5), open_price=1, high_price=2,
        low_price=0.5, close_price=close, volume=3,
    )


async def test_same_timestamp_different_intervals_are_stored_separately(db_session):
    db_session.add_all([_candle("1m"), _candle("5m"), _candle("1h")])

    await db_session.commit()


async def test_same_timestamp_same_interval_violates_unique_key(db_session):
    db_session.add_all([_candle("1m"), _candle("1m", close=2.0)])

    with pytest.raises(IntegrityError):
        await db_session.commit()


# ---------------------------------------------------------------------------
# POST /candles
# ---------------------------------------------------------------------------

async def test_create_candle_success(client):
    new_candle = {
        "exchange": "binance",
        "ticker": "ETH/USD",
        "interval": "1m",
        "open_price": 3500.0,
        "high_price": "3550.1",
        "low_price": 3490,
        "close_price": 3525.0,
        "volume": 88.5,
    }

    response = await client.post("/api/v1/market/candles", json=new_candle)

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["status"] == "success"
    assert body["message"] == "Candle created successfully"
    assert body["data"]["exchange"] == "binance"
    assert body["data"]["ticker"] == "ETH/USD"
    assert body["data"]["quote_currency"] == "USD"
    assert body["data"]["close_price"] == "3525.00000000"
    assert body["data"]["high_price"] == "3550.10000000"
    assert "id" in body["data"]  # DB assigned a real primary key

    # Integration check — candle is actually persisted
    get_response = await client.get("/api/v1/market/candles/ETH%2FUSD")
    get_body = get_response.json()
    assert len(get_body["data"]) == 1
    assert get_body["data"][0]["close_price"] == "3525.00000000"


async def test_create_candle_non_usd_quote_rejected(client):
    candle = {
        "exchange": "binance", "ticker": "BTC/USDT", "interval": "1m",
        "open_price": 1, "high_price": 1, "low_price": 1, "close_price": 1, "volume": 1,
    }

    response = await client.post("/api/v1/market/candles", json=candle)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "USD" in str(response.json()["detail"])


async def test_create_candle_unsupported_interval_rejected(client):
    candle = {
        "exchange": "binance", "ticker": "BTC/USD", "interval": "7m",
        "open_price": 1, "high_price": 1, "low_price": 1, "close_price": 1, "volume": 1,
    }

    response = await client.post("/api/v1/market/candles", json=candle)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_create_candle_invalid_negative_price(client):
    invalid_candle = {
        "exchange": "binance",
        "ticker": "BTC/USD",
        "interval": "1m",
        "open_price": -50.0,  # negative prices are rejected
        "high_price": 65000.0,
        "low_price": 64000.0,
        "close_price": 64500.0,
        "volume": 1.0,
    }

    response = await client.post("/api/v1/market/candles", json=invalid_candle)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_create_candle_non_numeric_price_rejected(client):
    candle = {
        "exchange": "binance", "ticker": "BTC/USD", "interval": "1m",
        "open_price": "abc", "high_price": 1, "low_price": 1, "close_price": 1, "volume": 1,
    }

    response = await client.post("/api/v1/market/candles", json=candle)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_create_candle_missing_exchange(client):
    invalid_candle = {
        # exchange missing — required field
        "ticker": "BTC/USD",
        "interval": "1m",
        "open_price": 65000.0,
        "high_price": 65300.0,
        "low_price": 64850.0,
        "close_price": 65200.0,
        "volume": 15.4,
    }

    response = await client.post("/api/v1/market/candles", json=invalid_candle)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_create_multiple_candles_same_ticker(client):
    candle = {
        "exchange": "binance",
        "ticker": "BTC/USD",
        "interval": "1m",
        "open_price": 65000.0,
        "high_price": 65300.0,
        "low_price": 64850.0,
        "close_price": 65200.0,
        "volume": 15.4,
        "timestamp": "2026-09-19T12:00:00",
    }

    await client.post("/api/v1/market/candles", json=candle)
    await client.post("/api/v1/market/candles", json={**candle, "timestamp": "2026-09-19T12:01:00"})

    get_response = await client.get("/api/v1/market/candles/BTC%2FUSD")
    assert len(get_response.json()["data"]) == 2


# ---------------------------------------------------------------------------
# WebSocket topic resolution — market list from the database
# ---------------------------------------------------------------------------

async def test_resolve_topics_uses_every_enabled_exchange_with_the_market(db_session, markets):
    # binance lists BTC/USDT, kraken BTC/USD — both feed the unified BTC/USD;
    # coinbase is disabled.
    topics = await _resolve_topics(db_session, "BTCUSD")

    assert topics == ["binance.BTCUSD.candles", "kraken.BTCUSD.candles"]


async def test_resolve_topics_accepts_native_spelling(db_session, markets):
    assert await _resolve_topics(db_session, "BTC-USDT") == [
        "binance.BTCUSD.candles", "kraken.BTCUSD.candles",
    ]


async def test_resolve_topics_filters_by_exchange(db_session, markets):
    assert await _resolve_topics(db_session, "BTCUSD", "KRAKEN") == ["kraken.BTCUSD.candles"]


async def test_resolve_topics_ignores_disabled_symbols_and_exchanges(db_session, markets):
    assert await _resolve_topics(db_session, "ETHUSD") == []
    assert await _resolve_topics(db_session, "BTCUSD", "coinbase") == []


async def test_resolve_topics_unknown_or_unsupported_market_is_empty(db_session, markets):
    assert await _resolve_topics(db_session, "DOGEUSD") == []
    assert await _resolve_topics(db_session, "ETHBTC") == []


# ---------------------------------------------------------------------------
# GET /markets — the market picker's data source
# ---------------------------------------------------------------------------

async def test_list_markets_merges_exchanges_per_unified_ticker(client, markets, db_session):
    from app.models.exchange import Symbol

    binance_id = markets["binance"].id
    db_session.add_all([
        Symbol(exchange_id=binance_id, ticker="BTC/USDT", interval="30s"),
        Symbol(exchange_id=binance_id, ticker="SOL/USDT", interval="1d"),
    ])
    await db_session.commit()

    response = await client.get("/api/v1/market/markets")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert [m["ticker"] for m in data] == ["BTC/USD", "SOL/USD"]
    btc = data[0]
    # binance feeds it from BTC/USDT, kraken from BTC/USD — one entry, both exchanges
    assert btc["exchanges"] == ["binance", "kraken"]
    assert btc["intervals"] == ["30s", "1m"]          # sorted shortest first
    assert data[1] == {"ticker": "SOL/USD", "exchanges": ["binance"], "intervals": ["1d"]}


async def test_list_markets_excludes_disabled_exchanges_and_symbols(client, markets):
    response = await client.get("/api/v1/market/markets")

    # ETH/USDT is a disabled symbol, coinbase is a disabled exchange
    tickers = [m["ticker"] for m in response.json()["data"]]
    assert tickers == ["BTC/USD"]
    assert "coinbase" not in response.json()["data"][0]["exchanges"]


async def test_list_markets_skips_rows_the_unified_feed_cannot_publish(client, markets, db_session):
    from app.models.exchange import Symbol

    db_session.add_all([
        Symbol(exchange_id=markets["binance"].id, ticker="ETH/BTC", interval="1m"),    # not USD-equivalent
        Symbol(exchange_id=markets["binance"].id, ticker="BTC/USDT", interval="15m"),  # unsupported interval
    ])
    await db_session.commit()

    response = await client.get("/api/v1/market/markets")

    data = response.json()["data"]
    assert [m["ticker"] for m in data] == ["BTC/USD"]
    assert data[0]["intervals"] == ["1m"]


async def test_list_markets_is_empty_without_configured_markets(client):
    response = await client.get("/api/v1/market/markets")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["data"] == []
    assert "0 market" in response.json()["message"]


async def test_list_markets_is_public(anonymous_client, markets):
    response = await anonymous_client.get("/api/v1/market/markets")

    assert response.status_code == status.HTTP_200_OK
