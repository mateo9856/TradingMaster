from typing import List, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.helpers.intervals import SUPPORTED_INTERVALS, validate_interval
from app.helpers.markets import split_symbol
from app.helpers.sources import NON_CCXT_SOURCES, POLL_METHOD, is_non_ccxt_source


def _normalize_ticker(value: str) -> str:
    """"btc-usdt" / "BTCUSDT" → "BTC/USDT", "pkn.wa/pln" → "PKN.WA/PLN"; rejects unsupported quotes."""
    base, quote = split_symbol(value)
    return f"{base}/{quote}"


def _dedupe(values: List[str]) -> List[str]:
    return list(dict.fromkeys(values))


# How the producer reads an exchange (app/kafka/producer.py):
#   multi  — one watchOHLCVForSymbols stream for many symbols
#   ohlcv  — one watchOHLCV stream per symbol
#   trades — candles built from watchTrades
#   poll   — a non-ccxt source polled for bars (Yahoo Finance stocks)
CollectionMethod = Literal["multi", "ohlcv", "trades", "poll"]


class ExchangeCreate(BaseModel):
    """
    A new exchange to collect from.

    `name` is validated strictly because it is not just a label: it becomes a
    ccxt class lookup (`getattr(ccxtpro, name)`), a segment of a Kafka topic
    name, and part of the Flink job's topic-pattern SQL literal. It used to be
    an unconstrained free-text field writable by any authenticated user.
    """

    name: str = Field(
        ..., examples=["binance"], min_length=2, max_length=32,
        pattern=r"^[a-z0-9_]+$",
        description="ccxt exchange id (or a registered non-ccxt source such as 'yahoo') — "
                    "lower-case letters, digits and underscores",
    )
    method: CollectionMethod = Field(..., examples=["multi", "ohlcv", "trades", "poll"])

    @field_validator("name")
    @classmethod
    def _known_to_ccxt(cls, value: str) -> str:
        """
        Reject an exchange ccxt has never heard of. Without this the producer
        would raise AttributeError on every reconnect for a name nobody can fix
        except by editing the database. Registered non-ccxt sources ("yahoo")
        are let through here and never reach ccxt — the producer dispatches
        them by name.
        """
        if is_non_ccxt_source(value):
            return value
        try:
            import ccxt.pro as ccxtpro
        except ImportError:      # ccxt isn't needed to validate in tests
            return value
        if value not in getattr(ccxtpro, "exchanges", []):
            raise ValueError(
                f"'{value}' is not a ccxt exchange id. Check the spelling against ccxt's list."
            )
        return value

    @model_validator(mode="after")
    def _method_matches_source(self) -> "ExchangeCreate":
        """A non-ccxt source has exactly one method; a ccxt exchange can't be polled."""
        if is_non_ccxt_source(self.name):
            expected = NON_CCXT_SOURCES[self.name]["method"]
            if self.method != expected:
                raise ValueError(f"'{self.name}' is collected with method '{expected}'")
        elif self.method == POLL_METHOD:
            raise ValueError(f"Method '{POLL_METHOD}' is only for: {', '.join(NON_CCXT_SOURCES)}")
        return self


class ExchangeResponse(BaseModel):
    id: int
    name: str
    method: str
    asset_class: str = "crypto"
    enabled: bool

    class Config:
        from_attributes = True


class SymbolCreate(BaseModel):
    ticker: str = Field(
        ..., examples=["BTC/USDT", "PKN.WA/PLN"],
        description="The exchange's market; quote must be USD, USDT, USDC or an ECB currency (EUR, PLN, …)",
    )
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
        default_factory=lambda: ["1m"], min_length=1, max_length=len(SUPPORTED_INTERVALS),
        examples=[list(SUPPORTED_INTERVALS)],
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


class MarketResponse(BaseModel):
    """One unified market, as published by the feed — see GET /api/v1/market/markets."""

    ticker: str = Field(..., examples=["BTC/USD"], description="Unified ticker; stored prices are in USD")
    asset_class: str = Field("crypto", examples=["crypto", "stock"])
    exchanges: List[str] = Field(..., examples=[["binance", "kraken"]], description="Exchanges feeding this market")
    intervals: List[str] = Field(..., examples=[list(SUPPORTED_INTERVALS)], description="Candle lengths collected")


class SymbolSkipped(BaseModel):
    ticker: str
    interval: str
    reason: str


class SymbolBulkResult(BaseModel):
    created: List[SymbolResponse]
    skipped: List[SymbolSkipped]
