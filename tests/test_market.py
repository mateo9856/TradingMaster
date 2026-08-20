import pytest
from fastapi import status

# ---------------------------------------------------------------------------
# GET /candles/{ticker}
# ---------------------------------------------------------------------------

async def test_get_candles_success(client, btc_candle):
    # btc_candle fixture seeds one BTC/USDT candle before the request
    response = await client.get("/api/v1/market/candles/BTC%2FUSDT")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["status"] == "success"
    assert len(body["data"]) == 1
    assert body["data"][0]["ticker"] == "BTC/USDT"
    assert body["data"][0]["close_price"] == 65200.0
    assert body["data"][0]["exchange"] == "binance"


async def test_get_candles_filter_by_exchange(client, multi_candles):
    # multi_candles has BTC/USDT from both binance and kraken
    response = await client.get("/api/v1/market/candles/BTC%2FUSDT?exchange=binance")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    # Only binance candles returned
    assert all(c["exchange"] == "binance" for c in body["data"])


async def test_get_candles_filter_by_interval(client, multi_candles):
    # multi_candles has BTC/USDT in both 1m and 5m intervals
    response = await client.get("/api/v1/market/candles/BTC%2FUSDT?interval=5m")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert all(c["interval"] == "5m" for c in body["data"])


async def test_get_candles_not_found(client):
    response = await client.get("/api/v1/market/candles/INVALID")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "nie został znaleziony" in response.json()["detail"]


async def test_get_candles_wrong_interval_returns_404(client, btc_candle):
    # btc_candle is 1m — querying 1h should return 404
    response = await client.get("/api/v1/market/candles/BTC%2FUSDT?interval=1h")

    assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# POST /candles
# ---------------------------------------------------------------------------

async def test_create_candle_success(client):
    new_candle = {
        "exchange": "binance",
        "ticker": "ETH/USDT",
        "interval": "1m",
        "open_price": 3500.0,
        "high_price": 3550.0,
        "low_price": 3490.0,
        "close_price": 3525.0,
        "volume": 88.5,
    }

    response = await client.post("/api/v1/market/candles", json=new_candle)

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["status"] == "success"
    assert body["message"] == "Candle created successfully"
    assert body["data"]["exchange"] == "binance"
    assert body["data"]["ticker"] == "ETH/USDT"
    assert body["data"]["close_price"] == 3525.0
    assert "id" in body["data"]  # DB assigned a real primary key

    # Integration check — candle is actually persisted
    get_response = await client.get("/api/v1/market/candles/ETH%2FUSDT")
    get_body = get_response.json()
    assert len(get_body["data"]) == 1
    assert get_body["data"][0]["close_price"] == 3525.0


async def test_create_candle_invalid_negative_price(client):
    invalid_candle = {
        "exchange": "binance",
        "ticker": "BTC/USDT",
        "interval": "1m",
        "open_price": -50.0,  # ge=0 must reject this
        "high_price": 65000.0,
        "low_price": 64000.0,
        "close_price": 64500.0,
        "volume": 1.0,
    }

    response = await client.post("/api/v1/market/candles", json=invalid_candle)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_create_candle_missing_exchange(client):
    invalid_candle = {
        # exchange missing — required field
        "ticker": "BTC/USDT",
        "interval": "1m",
        "open_price": 65000.0,
        "high_price": 65300.0,
        "low_price": 64850.0,
        "close_price": 65200.0,
        "volume": 15.4,
    }

    response = await client.post("/api/v1/market/candles", json=invalid_candle)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_create_multiple_candles_same_ticker(client):
    candle = {
        "exchange": "binance",
        "ticker": "BTC/USDT",
        "interval": "1m",
        "open_price": 65000.0,
        "high_price": 65300.0,
        "low_price": 64850.0,
        "close_price": 65200.0,
        "volume": 15.4,
    }

    await client.post("/api/v1/market/candles", json=candle)
    await client.post("/api/v1/market/candles", json={**candle, "close_price": 65500.0})

    get_response = await client.get("/api/v1/market/candles/BTC%2FUSDT")
    assert len(get_response.json()["data"]) == 2