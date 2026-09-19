"""
Unit tests for Pydantic schemas — no DB, no HTTP, pure validation.
"""

import json
from decimal import Decimal

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from app.schemas import ApiResponse, CandleBase, CandleCreate, CandleResponse


class TestCandleBase:

    def test_valid_candle(self):
        candle = CandleBase(
            exchange="binance",
            ticker="BTC/USDT",
            interval="1m",
            open_price=65000.0,
            high_price=65300.0,
            low_price=64850.0,
            close_price=65200.0,
            volume=15.4,
        )
        assert candle.ticker == "BTC/USDT"
        assert candle.exchange == "binance"

    def test_negative_open_price_rejected(self):
        with pytest.raises(ValidationError) as exc:
            CandleBase(
                exchange="binance", ticker="BTC/USDT", interval="1m",
                open_price=-1.0,   # ge=0 must reject this
                high_price=65300.0, low_price=64850.0,
                close_price=65200.0, volume=15.4,
            )
        assert "open_price" in str(exc.value)

    def test_negative_volume_rejected(self):
        with pytest.raises(ValidationError) as exc:
            CandleBase(
                exchange="binance", ticker="BTC/USDT", interval="1m",
                open_price=65000.0, high_price=65300.0, low_price=64850.0,
                close_price=65200.0, volume=-5.0,  # ge=0 must reject this
            )
        assert "volume" in str(exc.value)

    def test_zero_price_allowed(self):
        """Zero is a valid price (ge=0 not gt=0)."""
        candle = CandleBase(
            exchange="binance", ticker="BTC/USDT", interval="1m",
            open_price=0.0, high_price=0.0, low_price=0.0,
            close_price=0.0, volume=0.0,
        )
        assert candle.open_price == 0.0

    def test_default_interval_is_1m(self):
        candle = CandleBase(
            exchange="binance", ticker="BTC/USDT",
            open_price=100.0, high_price=110.0, low_price=90.0,
            close_price=105.0, volume=1.0,
        )
        assert candle.interval == "1m"


    def test_prices_are_exact_decimals(self):
        candle = CandleBase(
            exchange="binance", ticker="BTC/USD",
            open_price=0.1, high_price="0.2", low_price=Decimal("0.1"),
            close_price=0.30000000000000004, volume=1,
        )
        assert candle.open_price == Decimal("0.10000000")
        assert candle.close_price == Decimal("0.30000000")

    def test_prices_serialize_as_fixed_point_strings(self):
        candle = CandleBase(
            exchange="binance", ticker="BTC/USD",
            open_price=65000.1, high_price=65300, low_price="64850.5",
            close_price=65200.123456789, volume=15.4,
        )
        payload = json.loads(candle.model_dump_json())
        assert payload["open_price"] == "65000.10000000"
        assert payload["high_price"] == "65300.00000000"
        assert payload["close_price"] == "65200.12345679"
        assert payload["volume"] == "15.40000000"

    @pytest.mark.parametrize("price", ["abc", None, float("nan"), float("inf")])
    def test_non_numeric_price_rejected(self, price):
        with pytest.raises(ValidationError) as exc:
            CandleBase(
                exchange="binance", ticker="BTC/USD",
                open_price=price, high_price=1, low_price=1, close_price=1, volume=1,
            )
        assert "open_price" in str(exc.value)


class TestCandleCreate:

    @pytest.mark.parametrize("ticker", ["BTC/USD", "btc-usd", "BTCUSD"])
    def test_usd_ticker_normalized(self, ticker):
        candle = CandleCreate(
            exchange="binance", ticker=ticker,
            open_price=1, high_price=1, low_price=1, close_price=1, volume=1,
        )
        assert candle.ticker == "BTC/USD"

    @pytest.mark.parametrize("ticker", ["BTC/USDT", "BTC/USDC", "ETH/BTC", "INVALID"])
    def test_non_usd_ticker_rejected(self, ticker):
        with pytest.raises(ValidationError) as exc:
            CandleCreate(
                exchange="binance", ticker=ticker,
                open_price=1, high_price=1, low_price=1, close_price=1, volume=1,
            )
        assert "ticker" in str(exc.value)

    @pytest.mark.parametrize("interval", ["30s", "1m", "5m", "1h", "1d"])
    def test_supported_intervals_accepted(self, interval):
        candle = CandleCreate(
            exchange="binance", ticker="BTC/USD", interval=interval,
            open_price=1, high_price=1, low_price=1, close_price=1, volume=1,
        )
        assert candle.interval == interval

    @pytest.mark.parametrize("interval", ["7m", "15m", ""])
    def test_unsupported_interval_rejected(self, interval):
        with pytest.raises(ValidationError) as exc:
            CandleCreate(
                exchange="binance", ticker="BTC/USD", interval=interval,
                open_price=1, high_price=1, low_price=1, close_price=1, volume=1,
            )
        assert "interval" in str(exc.value)

    def test_timestamp_defaults_to_now(self):
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        candle = CandleCreate(
            exchange="binance", ticker="BTC/USD", interval="1m",
            open_price=65000.0, high_price=65300.0, low_price=64850.0,
            close_price=65200.0, volume=15.4,
        )
        after = datetime.now(timezone.utc).replace(tzinfo=None)
        assert before <= candle.timestamp <= after

    def test_explicit_timestamp_accepted(self):
        ts = datetime(2026, 1, 1, 12, 0, 0)
        candle = CandleCreate(
            exchange="binance", ticker="BTC/USD", interval="1m",
            open_price=65000.0, high_price=65300.0, low_price=64850.0,
            close_price=65200.0, volume=15.4, timestamp=ts,
        )
        assert candle.timestamp == ts


class TestCandleResponse:

    def test_from_dict(self):
        data = {
            "id": 1,
            "exchange": "binance",
            "ticker": "BTC/USDT",
            "interval": "1m",
            "timestamp": datetime(2026, 6, 23, 12, 0, 0),
            "open_price": 65000.0,
            "high_price": 65300.0,
            "low_price": 64850.0,
            "close_price": 65200.0,
            "volume": 15.4,
        }
        response = CandleResponse.model_validate(data)
        assert response.id == 1
        assert response.close_price == 65200.0
        assert response.source_ticker is None
        assert response.fx_rate is None

    def test_unified_fields_serialized(self):
        response = CandleResponse(
            id=1, exchange="binance", ticker="BTC/USD", interval="1m",
            timestamp=datetime(2026, 6, 23, 12), open_price=1, high_price=1,
            low_price=1, close_price=1, volume=1,
            source_ticker="BTC/USDT", quote_currency="USD", fx_rate=Decimal("0.9998"),
        )
        payload = json.loads(response.model_dump_json())
        assert payload["source_ticker"] == "BTC/USDT"
        assert payload["quote_currency"] == "USD"
        assert payload["fx_rate"] == "0.99980000"

    def test_missing_id_rejected(self):
        with pytest.raises(ValidationError):
            CandleResponse(
                exchange="binance", ticker="BTC/USDT", interval="1m",
                timestamp=datetime.now(),
                open_price=65000.0, high_price=65300.0,
                low_price=64850.0, close_price=65200.0, volume=15.4,
                # id missing — required field
            )


class TestApiResponse:

    def test_wraps_data_correctly(self):
        response = ApiResponse(
            status="success",
            message="OK",
            data={"key": "value"},
        )
        assert response.status == "success"
        assert response.data == {"key": "value"}

    def test_data_can_be_none(self):
        response = ApiResponse(status="error", message="Something went wrong")
        assert response.data is None

    def test_message_is_optional(self):
        response = ApiResponse(status="success", data=[])
        assert response.message is None
