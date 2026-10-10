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


@pytest.mark.parametrize("ticker", ["INVALID", "ETH%2FBTC", "BTC%2FXYZ"])
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
    assert data[1] == {"ticker": "SOL/USD", "asset_class": "crypto", "exchanges": ["binance"], "intervals": ["1d"]}


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


# ---------------------------------------------------------------------------
# Live stream admission control
#
# Every viewer used to get its own Kafka consumer and there was no cap at all,
# so connections were limited only by what a client chose to open.
# ---------------------------------------------------------------------------

def test_connections_are_capped_per_client(monkeypatch):
    from app.routers import market

    monkeypatch.setattr(market, "_open_connections", 0)
    monkeypatch.setattr(market, "_connections_per_ip", {})
    monkeypatch.setattr(market, "WS_MAX_CONNECTIONS_PER_IP", 2)
    monkeypatch.setattr(market, "WS_MAX_CONNECTIONS", 100)

    assert market._admit("1.2.3.4")[0] is True
    assert market._admit("1.2.3.4")[0] is True

    admitted, reason = market._admit("1.2.3.4")
    assert admitted is False
    assert reason == "per_client_capacity"

    # A different client is unaffected by one noisy neighbour.
    assert market._admit("5.6.7.8")[0] is True


def test_connections_are_capped_for_the_whole_process(monkeypatch):
    from app.routers import market

    monkeypatch.setattr(market, "_open_connections", 0)
    monkeypatch.setattr(market, "_connections_per_ip", {})
    monkeypatch.setattr(market, "WS_MAX_CONNECTIONS", 2)
    monkeypatch.setattr(market, "WS_MAX_CONNECTIONS_PER_IP", 100)

    assert market._admit("1.1.1.1")[0] is True
    assert market._admit("2.2.2.2")[0] is True

    admitted, reason = market._admit("3.3.3.3")
    assert admitted is False
    assert reason == "server_capacity"


def test_releasing_a_slot_lets_the_next_client_in(monkeypatch):
    from app.routers import market

    monkeypatch.setattr(market, "_open_connections", 0)
    monkeypatch.setattr(market, "_connections_per_ip", {})
    monkeypatch.setattr(market, "WS_MAX_CONNECTIONS", 1)
    monkeypatch.setattr(market, "WS_MAX_CONNECTIONS_PER_IP", 1)

    assert market._admit("1.2.3.4")[0] is True
    assert market._admit("1.2.3.4")[0] is False

    market._release("1.2.3.4")

    assert market._admit("1.2.3.4")[0] is True
    # The per-IP map must not keep an entry once the client has gone, or it
    # grows for every address that ever connected.
    market._release("1.2.3.4")
    assert market._connections_per_ip == {}


async def test_the_pump_filters_to_the_requested_interval():
    """
    The UI used to receive every interval and discard the unwanted ones in the
    browser; filtering here keeps them off the wire.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.kafka.stream_hub import Subscription
    from app.routers.market import _pump

    subscription = Subscription(("t",), maxsize=10)
    subscription.offer({"interval": "1m", "close_price": "1"})
    subscription.offer({"interval": "5m", "close_price": "2"})
    subscription.offer({"interval": "1m", "close_price": "3"})

    websocket = MagicMock()
    sent = []

    async def send_json(payload):
        sent.append(payload)
        if len(sent) == 2:
            raise asyncio.CancelledError      # stop the pump

    websocket.send_json = AsyncMock(side_effect=send_json)

    with pytest.raises(asyncio.CancelledError):
        await _pump(websocket, subscription, wanted_interval="1m")

    assert [p["close_price"] for p in sent] == ["1", "3"]
