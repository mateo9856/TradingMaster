from typing import List

from pydantic import BaseModel, Field, field_validator

from app.helpers.intervals import SUPPORTED_INTERVALS, validate_interval
from app.helpers.markets import split_symbol


def _normalize_ticker(value: str) -> str:
    """"btc-usdt" / "BTCUSDT" → "BTC/USDT"; rejects non-USD-equivalent quotes."""
    base, quote = split_symbol(value)
    return f"{base}/{quote}"


def _dedupe(values: List[str]) -> List[str]:
    return list(dict.fromkeys(values))


class ExchangeCreate(BaseModel):
    name: str = Field(..., examples=["binance"])
    method: str = Field(..., examples=["multi", "ohlcv", "trades"])


class ExchangeResponse(BaseModel):
    id: int
    name: str
    method: str
    enabled: bool

    class Config:
        from_attributes = True


class SymbolCreate(BaseModel):
    ticker: str = Field(..., examples=["BTC/USDT"], description="The exchange's market; quote must be USD, USDT or USDC")
    interval: str = Field("1m", examples=list(SUPPORTED_INTERVALS))

    @field_validator("ticker")
    @classmethod
    def _ticker(cls, value: str) -> str:
        return _normalize_ticker(value)

    @field_validator("interval")
    @classmethod
    def _interval(cls, value: str) -> str:
        return validate_interval(value)


class SymbolBulkCreate(BaseModel):
    tickers: List[str] = Field(..., min_length=1, max_length=200, examples=[["SOL/USDT", "XRP/USDT"]])
    intervals: List[str] = Field(
        default_factory=lambda: ["1m"], min_length=1, examples=[list(SUPPORTED_INTERVALS)],
    )

    @field_validator("tickers")
    @classmethod
    def _tickers(cls, values: List[str]) -> List[str]:
        return _dedupe([_normalize_ticker(v) for v in values])

    @field_validator("intervals")
    @classmethod
    def _intervals(cls, values: List[str]) -> List[str]:
        return _dedupe([validate_interval(v) for v in values])


class SymbolResponse(BaseModel):
    id: int
    exchange_id: int
    ticker: str
    interval: str
    enabled: bool

    class Config:
        from_attributes = True


class SymbolSkipped(BaseModel):
    ticker: str
    interval: str
    reason: str


class SymbolBulkResult(BaseModel):
    created: List[SymbolResponse]
    skipped: List[SymbolSkipped]
