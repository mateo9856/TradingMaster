"""
Unit tests for Pydantic schemas — no DB, no HTTP, pure validation.
"""

import pytest
from datetime import datetime
from pydantic import ValidationError

from app.models.candle import CandleBase, CandleCreate, CandleResponse
from app.models.api_response import ApiResponse


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


class TestCandleCreate:

    def test_timestamp_defaults_to_now(self):
        before = datetime.now()
        candle = CandleCreate(
            exchange="binance", ticker="BTC/USDT", interval="1m",
            open_price=65000.0, high_price=65300.0, low_price=64850.0,
            close_price=65200.0, volume=15.4,
        )
        after = datetime.now()
        assert before <= candle.timestamp <= after

    def test_explicit_timestamp_accepted(self):
        ts = datetime(2026, 1, 1, 12, 0, 0)
        candle = CandleCreate(
            exchange="binance", ticker="BTC/USDT", interval="1m",
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