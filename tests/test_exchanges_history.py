import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest


async def test_list_exchanges_returns_alphabetical_rows(client, db_session):
    from app.models.exchange import Exchange

    db_session.add_all([
        Exchange(name="kraken", method="ohlcv"),
        Exchange(name="binance", method="multi"),
    ])
    await db_session.commit()

    response = await client.get("/api/v1/exchanges")

    assert response.status_code == 200
    assert [row["name"] for row in response.json()["data"]] == ["binance", "kraken"]


async def test_create_exchange_and_reject_duplicate(client):
    payload = {"name": "coinbase", "method": "trades"}

    created = await client.post("/api/v1/exchanges", json=payload)
    duplicate = await client.post("/api/v1/exchanges", json=payload)

    assert created.status_code == 201
    assert created.json()["data"]["enabled"] is True
    assert duplicate.status_code == 400
    assert "already exists" in duplicate.json()["detail"]


async def test_toggle_exchange_changes_enabled_state(client, exchange):
    response = await client.put(f"/api/v1/exchanges/{exchange.id}/toggle")

    assert response.status_code == 200
    assert response.json()["data"]["enabled"] is False


async def test_toggle_missing_exchange_returns_404(client):
    response = await client.put("/api/v1/exchanges/999/toggle")

    assert response.status_code == 404
    assert response.json()["detail"] == "Exchange not found"


async def test_symbol_crud_and_missing_exchange_validation(client, exchange):
    created = await client.post(
        f"/api/v1/exchanges/{exchange.id}/symbols",
        json={"ticker": "BTC/USDT", "interval": "5m"},
    )
    listed = await client.get(f"/api/v1/exchanges/{exchange.id}/symbols")
    toggled = await client.put(
        f"/api/v1/exchanges/symbols/{created.json()['data']['id']}/toggle"
    )
    missing = await client.post(
        "/api/v1/exchanges/999/symbols",
        json={"ticker": "ETH/USDT"},
    )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()["data"][0]["interval"] == "5m"
    assert toggled.status_code == 200
    assert toggled.json()["data"]["enabled"] is False
    assert missing.status_code == 404


async def test_history_filters_by_date_exchange_and_interval(client, history_candles):
    response = await client.get(
        "/api/v1/history/BTC%2FUSD",
        params={
            "date_from": "2026-06-22",
            "date_to": "2026-06-23",
            "exchange": "BINANCE",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert len(body["data"]) == 1
    assert body["data"][0]["ticker"] == "BTC/USD"
    assert body["data"][0]["source_ticker"] == "BTC/USDT"
    assert body["data"][0]["close_price"] == "65200.00000000"
    assert body["data"][0]["trade_date"] == "2026-06-22"


async def test_history_limit_and_not_found(client, history_candles):
    response = await client.get(
        "/api/v1/history/BTC/USD",
        params={"date_from": "2026-06-22", "date_to": "2026-06-23", "limit": 1},
    )
    not_found = await client.get(
        "/api/v1/history/DOGE%2FUSD",
        params={"date_from": "2026-06-22", "date_to": "2026-06-23"},
    )

    assert response.status_code == 200
    assert len(response.json()["data"]) == 1
    assert not_found.status_code == 404


async def test_archive_endpoint_starts_background_job(client):
    with patch("app.jobs.eod_archive.run_eod_job", new_callable=AsyncMock) as job:
        response = await client.post("/api/v1/history/archive/2026-06-23")
        await asyncio.sleep(0)

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    job.assert_awaited_once_with(date(2026, 6, 23))


async def test_history_resolves_native_ticker_to_unified(client, history_candles):
    response = await client.get(
        "/api/v1/history/BTCUSDT",
        params={"date_from": "2026-06-22", "date_to": "2026-06-23"},
    )

    assert response.status_code == 200
    assert {row["ticker"] for row in response.json()["data"]} == {"BTC/USD"}
    assert {row["exchange"] for row in response.json()["data"]} == {"binance", "kraken"}


async def test_history_unsupported_quote_returns_422(client, history_candles):
    response = await client.get(
        "/api/v1/history/ETH%2FBTC",
        params={"date_from": "2026-06-22", "date_to": "2026-06-23"},
    )

    assert response.status_code == 422


# ── Symbols: intervals, quotes, duplicates ───────────────────────────────────

@pytest.mark.parametrize("interval", ["30s", "1m", "5m", "1h", "1d"])
async def test_create_symbol_accepts_every_supported_interval(client, exchange, interval):
    response = await client.post(
        f"/api/v1/exchanges/{exchange.id}/symbols",
        json={"ticker": "BTC/USDT", "interval": interval},
    )

    assert response.status_code == 201
    assert response.json()["data"]["interval"] == interval


async def test_create_symbol_normalizes_ticker_spelling(client, exchange):
    response = await client.post(
        f"/api/v1/exchanges/{exchange.id}/symbols",
        json={"ticker": "sol-usdt"},
    )

    assert response.status_code == 201
    assert response.json()["data"]["ticker"] == "SOL/USDT"


@pytest.mark.parametrize("payload", [
    {"ticker": "BTC/USDT", "interval": "7m"},
    {"ticker": "BTC/USDT", "interval": "15m"},
    {"ticker": "ETH/BTC", "interval": "1m"},
    {"ticker": "BTC/EUR", "interval": "1m"},
    {"ticker": "", "interval": "1m"},
])
async def test_create_symbol_rejects_unsupported_interval_or_quote(client, exchange, payload):
    response = await client.post(f"/api/v1/exchanges/{exchange.id}/symbols", json=payload)

    assert response.status_code == 422


async def test_create_symbol_duplicate_returns_409(client, exchange):
    payload = {"ticker": "BTC/USDT", "interval": "5m"}

    first = await client.post(f"/api/v1/exchanges/{exchange.id}/symbols", json=payload)
    duplicate = await client.post(f"/api/v1/exchanges/{exchange.id}/symbols", json=payload)

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


async def test_create_symbol_unified_ticker_clash_returns_409(client, exchange):
    # BTC/USDT and BTC/USD on one exchange would both publish the unified BTC/USD.
    await client.post(f"/api/v1/exchanges/{exchange.id}/symbols", json={"ticker": "BTC/USDT"})
    clash = await client.post(f"/api/v1/exchanges/{exchange.id}/symbols", json={"ticker": "BTC/USD"})
    other_interval = await client.post(
        f"/api/v1/exchanges/{exchange.id}/symbols", json={"ticker": "BTC/USD", "interval": "1h"},
    )

    assert clash.status_code == 409
    assert "BTC/USDT already feeds BTC/USD" in clash.json()["detail"]
    assert other_interval.status_code == 201


async def test_create_symbol_requires_authentication(anonymous_client, exchange):
    response = await anonymous_client.post(
        f"/api/v1/exchanges/{exchange.id}/symbols", json={"ticker": "BTC/USDT"},
    )

    assert response.status_code == 401


# ── Symbols: bulk create ─────────────────────────────────────────────────────

async def test_bulk_create_symbols_creates_every_ticker_interval_pair(client, exchange):
    response = await client.post(
        f"/api/v1/exchanges/{exchange.id}/symbols/bulk",
        json={"tickers": ["BTC/USDT", "eth-usdt", "SOLUSDT"], "intervals": ["30s", "1m", "1d"]},
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert len(data["created"]) == 9
    assert data["skipped"] == []
    assert {(s["ticker"], s["interval"]) for s in data["created"]} == {
        (t, i) for t in ("BTC/USDT", "ETH/USDT", "SOL/USDT") for i in ("30s", "1m", "1d")
    }
    listed = await client.get(f"/api/v1/exchanges/{exchange.id}/symbols")
    assert len(listed.json()["data"]) == 9


async def test_bulk_create_symbols_defaults_to_1m(client, exchange):
    response = await client.post(
        f"/api/v1/exchanges/{exchange.id}/symbols/bulk", json={"tickers": ["BTC/USDT"]},
    )

    assert [s["interval"] for s in response.json()["data"]["created"]] == ["1m"]


async def test_bulk_create_symbols_skips_existing_and_clashing(client, exchange):
    await client.post(f"/api/v1/exchanges/{exchange.id}/symbols", json={"ticker": "BTC/USDT"})

    response = await client.post(
        f"/api/v1/exchanges/{exchange.id}/symbols/bulk",
        json={"tickers": ["BTC/USDT", "BTC/USD", "ETH/USDT"], "intervals": ["1m"]},
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert [(s["ticker"], s["interval"]) for s in data["created"]] == [("ETH/USDT", "1m")]
    reasons = {s["ticker"]: s["reason"] for s in data["skipped"]}
    assert "already exists" in reasons["BTC/USDT"]
    assert "already feeds BTC/USD" in reasons["BTC/USD"]


async def test_bulk_create_symbols_unknown_exchange_returns_404(client):
    response = await client.post(
        "/api/v1/exchanges/999/symbols/bulk", json={"tickers": ["BTC/USDT"]},
    )

    assert response.status_code == 404


@pytest.mark.parametrize("payload", [
    {"tickers": []},
    {"tickers": ["BTC/USDT"], "intervals": []},
    {"tickers": ["BTC/USDT"], "intervals": ["2m"]},
    {"tickers": ["ETH/BTC"]},
])
async def test_bulk_create_symbols_validation_errors(client, exchange, payload):
    response = await client.post(f"/api/v1/exchanges/{exchange.id}/symbols/bulk", json=payload)

    assert response.status_code == 422


async def test_bulk_create_symbols_requires_authentication(anonymous_client, exchange):
    response = await anonymous_client.post(
        f"/api/v1/exchanges/{exchange.id}/symbols/bulk", json={"tickers": ["BTC/USDT"]},
    )

    assert response.status_code == 401
