from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer, field_validator

from app.helpers.intervals import validate_interval
from app.helpers.markets import UNIFIED_QUOTE, split_symbol
from app.helpers.prices import format_decimal, to_decimal
from app.helpers.time import utc_now_naive

# Unified-feed number format: accepts numbers or numeric strings, stores an
# exact non-negative Decimal with 8 decimals, and always serializes to JSON as
# a fixed-point string ("65000.10000000") — identical for every exchange.
Price = Annotated[
    Decimal,
    BeforeValidator(to_decimal),
    PlainSerializer(format_decimal, return_type=str, when_used="json"),
]


class CandleBase(BaseModel):
    exchange: str = Field(..., examples=["binance"])
    ticker: str = Field(..., examples=["BTC/USD"], description="Unified ticker — prices are always in USD")
    interval: str = Field("1m", examples=["30s", "1m", "5m", "1h", "1d"])
    open_price: Price = Field(..., description="Open price (USD)", examples=["65000.10000000"])
    high_price: Price = Field(..., description="Highest price (USD)", examples=["65300.00000000"])
    low_price: Price = Field(..., description="Lowest price (USD)", examples=["64850.00000000"])
    close_price: Price = Field(..., description="Closing price (USD)", examples=["65200.00000000"])
    volume: Price = Field(..., description="Trading volume in base currency units", examples=["15.40000000"])


class CandleCreate(CandleBase):
    timestamp: datetime = Field(default_factory=utc_now_naive)

    @field_validator("ticker")
    @classmethod
    def _usd_ticker(cls, value: str) -> str:
        # A manual insert carries no FX rate, so it must already be in USD.
        base, quote = split_symbol(value)
        if quote != UNIFIED_QUOTE:
            raise ValueError(f"Manual candles must be quoted in {UNIFIED_QUOTE} (e.g. {base}/{UNIFIED_QUOTE})")
        return f"{base}/{UNIFIED_QUOTE}"

    @field_validator("interval")
    @classmethod
    def _supported_interval(cls, value: str) -> str:
        return validate_interval(value)


class CandleResponse(CandleBase):
    id: int
    timestamp: datetime = Field(..., description="Timestamp of the candle")
    source_ticker: Optional[str] = Field(None, description="The exchange's own market, e.g. BTC/USDT")
    quote_currency: Optional[str] = Field(None, examples=["USD"])
    fx_rate: Optional[Price] = Field(None, description="Rate applied to convert the native quote to USD")

    class Config:
        from_attributes = True
