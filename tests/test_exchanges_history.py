import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch


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
        "/api/v1/history/BTC%2FUSDT",
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
    assert body["data"][0]["ticker"] == "BTC/USDT"
    assert body["data"][0]["trade_date"] == "2026-06-22"


async def test_history_limit_and_not_found(client, history_candles):
    response = await client.get(
        "/api/v1/history/BTC/USDT",
        params={"date_from": "2026-06-22", "date_to": "2026-06-23", "limit": 1},
    )
    not_found = await client.get(
        "/api/v1/history/DOGE%2FUSDT",
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
