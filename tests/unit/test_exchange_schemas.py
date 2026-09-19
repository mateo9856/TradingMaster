import json
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.schemas import CandleHistoryResponse, ExchangeCreate, SymbolBulkCreate, SymbolCreate


def test_exchange_and_symbol_schema_defaults():
    assert ExchangeCreate(name="binance", method="multi").name == "binance"
    assert SymbolCreate(ticker="BTC/USDT").interval == "1m"


@pytest.mark.parametrize("interval", ["30s", "1m", "5m", "1h", "1d"])
def test_symbol_create_accepts_supported_intervals(interval):
    assert SymbolCreate(ticker="BTC/USDT", interval=interval).interval == interval


@pytest.mark.parametrize("interval", ["7m", "15m", "1w", ""])
def test_symbol_create_rejects_unsupported_interval(interval):
    with pytest.raises(ValidationError, match="Unsupported interval"):
        SymbolCreate(ticker="BTC/USDT", interval=interval)


@pytest.mark.parametrize("ticker, expected", [
    ("BTC/USDT", "BTC/USDT"),
    ("btc-usdc", "BTC/USDC"),
    ("SOLUSD", "SOL/USD"),
])
def test_symbol_create_normalizes_ticker(ticker, expected):
    assert SymbolCreate(ticker=ticker).ticker == expected


@pytest.mark.parametrize("ticker", ["ETH/BTC", "BTC/EUR", "", "/USDT"])
def test_symbol_create_rejects_non_usd_or_malformed_ticker(ticker):
    with pytest.raises(ValidationError):
        SymbolCreate(ticker=ticker)


def test_symbol_bulk_create_normalizes_and_dedupes():
    body = SymbolBulkCreate(tickers=["btc-usdt", "BTCUSDT", "ETH/USD"], intervals=["1m", "30s", "1m"])

    assert body.tickers == ["BTC/USDT", "ETH/USD"]
    assert body.intervals == ["1m", "30s"]


def test_symbol_bulk_create_defaults_to_1m():
    assert SymbolBulkCreate(tickers=["BTC/USDT"]).intervals == ["1m"]


@pytest.mark.parametrize("payload", [
    {"tickers": []},
    {"tickers": ["BTC/USDT"], "intervals": []},
    {"tickers": ["BTC/USDT"], "intervals": ["3m"]},
    {"tickers": ["BTC/USDT", "ETH/BTC"]},
    {"tickers": [f"C{i}/USDT" for i in range(201)]},
])
def test_symbol_bulk_create_rejects_invalid_payload(payload):
    with pytest.raises(ValidationError):
        SymbolBulkCreate(**payload)


def test_history_response_validates_orm_shaped_data():
    response = CandleHistoryResponse.model_validate({
        "id": 1,
        "exchange": "binance",
        "ticker": "BTC/USD",
        "interval": "1m",
        "trade_date": date(2026, 6, 23),
        "timestamp": datetime(2026, 6, 23, 12, 0),
        "open_price": 1.0,
        "high_price": 2.0,
        "low_price": 0.5,
        "close_price": 1.5,
        "volume": 10.0,
        "source_ticker": "BTC/USDT",
        "quote_currency": "USD",
        "fx_rate": "0.9998",
        "archived_at": datetime(2026, 6, 24, 0, 0),
    })

    assert response.trade_date == date(2026, 6, 23)
    payload = json.loads(response.model_dump_json())
    assert payload["close_price"] == "1.50000000"
    assert payload["fx_rate"] == "0.99980000"


def test_history_response_rejects_negative_price():
    with pytest.raises(ValidationError):
        CandleHistoryResponse.model_validate({
            "id": 1, "exchange": "binance", "ticker": "BTC/USD", "interval": "1m",
            "trade_date": date(2026, 6, 23), "timestamp": datetime(2026, 6, 23, 12),
            "open_price": -1, "high_price": 1, "low_price": 1, "close_price": 1, "volume": 1,
            "archived_at": datetime(2026, 6, 24),
        })
