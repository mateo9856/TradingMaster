"""Public provider bid/ask snapshots. Never substitute candle closes for quotes."""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import ccxt.async_support as ccxt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.helpers.markets import QUOTE_PREFERENCE, source_ticker_candidates
from app.helpers.prices import to_decimal
from app.helpers.time import utc_now_naive
from app.models.exchange import Exchange, Symbol
from app.models.fiat_rate import FiatRate


class QuoteUnavailable(ValueError):
    """No usable bid/ask, trading session, or USD conversion is available."""


@dataclass(frozen=True)
class MarketSource:
    exchange: str
    ticker: str
    source_ticker: str
    asset_class: str


@dataclass(frozen=True)
class PriceQuote:
    bid: Decimal
    ask: Decimal
    source_at: datetime | None
    received_at: datetime
    delayed: bool = False
    session_end: datetime | None = None


def timestamp(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, timezone.utc).replace(tzinfo=None)


def validate_quote(quote: PriceQuote, now: datetime | None = None) -> None:
    now = now or utc_now_naive()
    if (not quote.bid.is_finite() or not quote.ask.is_finite()
            or quote.bid <= 0 or quote.ask < quote.bid):
        raise QuoteUnavailable("Missing, nonpositive, or crossed bid/ask")
    age_limit = (config.TRADING_STOCK_MAX_AGE_SECONDS if quote.delayed
                 else config.TRADING_CRYPTO_MAX_AGE_SECONDS)
    # Some exchanges omit order-book timestamps. In that case only a freshly
    # fetched book is usable; source_at remains NULL rather than inventing it.
    source_time = quote.source_at or quote.received_at
    if not -5 <= (now - source_time).total_seconds() <= age_limit:
        raise QuoteUnavailable("Provider quote is stale")
    if not -5 <= (now - quote.received_at).total_seconds() <= 15:
        raise QuoteUnavailable("Quote retrieval is stale")
    if quote.delayed and (quote.source_at is None or quote.session_end is None or now >= quote.session_end):
        raise QuoteUnavailable("Stock market is closed or session metadata is unavailable")


async def resolve_source(db: AsyncSession, exchange: str, ticker: str,
                         exact_source: str | None = None) -> MarketSource:
    rows = (await db.execute(
        select(Exchange, Symbol).join(Symbol)
        .where(Exchange.name == exchange, Exchange.enabled.is_(True), Symbol.enabled.is_(True),
               Symbol.ticker.in_(source_ticker_candidates(ticker)))
    )).all()
    if exact_source is not None:
        rows = [(e, s) for e, s in rows if s.ticker == exact_source]
    if not rows:
        raise QuoteUnavailable("Market is disabled or unavailable")
    exchange_row, symbol = min(rows, key=lambda row: QUOTE_PREFERENCE.index(row[1].ticker.split("/")[1]))
    return MarketSource(exchange, ticker, symbol.ticker, exchange_row.asset_class)


async def fetch_crypto(source: MarketSource) -> PriceQuote:
    if source.exchange not in ccxt.exchanges:
        raise QuoteUnavailable("Unsupported quote provider")
    exchange = getattr(ccxt, source.exchange)({"enableRateLimit": True, "timeout": 8000})
    try:
        book = await exchange.fetch_order_book(source.source_ticker)
        received = utc_now_naive()
        if not book.get("bids") or not book.get("asks"):
            raise QuoteUnavailable("Order book has no bid or ask")
        return PriceQuote(
            to_decimal(book["bids"][0][0]), to_decimal(book["asks"][0][0]),
            timestamp(book["timestamp"] / 1000) if book.get("timestamp") else None,
            received,
        )
    finally:
        await exchange.close()


def fetch_stock(source: MarketSource) -> PriceQuote:
    import yfinance as yf

    symbol, currency = source.source_ticker.split("/")
    ticker = yf.Ticker(symbol)
    info = ticker.get_info()
    metadata = ticker.get_history_metadata()
    regular = (metadata.get("currentTradingPeriod") or {}).get("regular") or {}
    now = utc_now_naive()
    if (info.get("currency") != currency or not info.get("regularMarketTime")
            or not regular.get("start") or not regular.get("end")):
        raise QuoteUnavailable("Stock quote currency, time, or session metadata is unavailable")
    if (not timestamp(regular["start"]) <= now < timestamp(regular["end"])
            or info.get("marketState", "REGULAR") != "REGULAR"):
        raise QuoteUnavailable("Stock market is closed")
    return PriceQuote(
        to_decimal(info.get("bid")), to_decimal(info.get("ask")),
        timestamp(info["regularMarketTime"]), now,
        delayed=True, session_end=timestamp(regular["end"]),
    )


async def usd_rate(db: AsyncSession, currency: str) -> Decimal:
    if currency == "USD":
        return Decimal(1)
    if currency in ("USDT", "USDC"):
        # A dedicated public fetch also works when the candle producer is down.
        source = MarketSource(config.FX_REFERENCE_EXCHANGE, f"{currency}/USD", f"{currency}/USD", "crypto")
        quote = await fetch_crypto(source)
        validate_quote(quote)
        return to_decimal((quote.bid + quote.ask) / 2)
    today = utc_now_naive().date()
    rate = await db.scalar(
        select(FiatRate).where(FiatRate.currency == currency, FiatRate.rate_date <= today,
                              FiatRate.rate_date >= today - timedelta(days=7))
        .order_by(FiatRate.rate_date.desc()).limit(1)
    )
    if rate is None or rate.units_per_usd <= 0:
        raise QuoteUnavailable("No recent USD conversion rate")
    return to_decimal(Decimal(1) / rate.units_per_usd)


class QuoteService:
    """Bound concurrent public requests; cache only successful snapshots for 2s."""

    def __init__(self):
        self._cache: dict[MarketSource, tuple[float, PriceQuote, Decimal]] = {}
        self._semaphore = asyncio.Semaphore(8)

    async def get(self, db: AsyncSession, source: MarketSource,
                  conversion_rate: Decimal | None = None) -> tuple[PriceQuote, Decimal]:
        cached = self._cache.get(source)
        if cached is not None and time.monotonic() - cached[0] < 2:
            validate_quote(cached[1])
            return cached[1], cached[2]
        try:
            async with asyncio.timeout(12):
                async with self._semaphore:
                    native = (await asyncio.to_thread(fetch_stock, source) if source.asset_class == "stock"
                              else await fetch_crypto(source))
                    validate_quote(native)
                    rate = (conversion_rate if conversion_rate is not None
                            else await usd_rate(db, source.source_ticker.split("/")[1]))
                    quote = PriceQuote(
                        to_decimal(native.bid * rate), to_decimal(native.ask * rate),
                        native.source_at, native.received_at, native.delayed, native.session_end,
                    )
                    validate_quote(quote)
            # Keep memory bounded even if markets are repeatedly reconfigured.
            self._cache = {key: value for key, value in self._cache.items()
                           if time.monotonic() - value[0] < 2}
            self._cache[source] = (time.monotonic(), quote, rate)
            return quote, rate
        except QuoteUnavailable:
            raise
        except Exception as exc:
            raise QuoteUnavailable("Quote provider is unavailable") from exc


quote_service = QuoteService()
