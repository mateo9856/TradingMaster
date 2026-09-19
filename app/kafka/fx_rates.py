"""
USD conversion rates for the unified market feed.

The feed publishes every price in USD. Markets quoted in a USD stablecoin
(USDT, USDC) are converted with the live USDT/USD and USDC/USD prices from a
reference exchange (FX_REFERENCE_EXCHANGE, Kraken by default), streamed
over CCXT Pro. When no rate has arrived yet, or the last one is older than
FX_MAX_AGE_SECONDS, conversion falls back to the 1:1 peg — collection never
stops because of a missing rate — and `fx_rate_fallback_total` is incremented
so the fallback is visible on the dashboard.
"""

import asyncio
import logging
import time
from decimal import Decimal
from typing import Callable, Optional

import ccxt.pro as ccxtpro

from app.config import FX_MAX_AGE_SECONDS, FX_REFERENCE_EXCHANGE
from app.helpers.markets import UNIFIED_QUOTE, USD_EQUIVALENT_QUOTES
from app.helpers.prices import to_decimal
from app.helpers.tasks import run_all
from app.metrics import fx_rate as fx_rate_gauge
from app.metrics import fx_rate_fallback_total

logger = logging.getLogger(__name__)

PEG_RATE = Decimal("1.00000000")
RATE_SOURCE_IDENTITY = "identity"
RATE_SOURCE_LIVE = "live"
RATE_SOURCE_PEG = "peg"

# Stablecoins converted to USD — every USD-equivalent quote except USD itself.
CONVERTED_QUOTES: tuple[str, ...] = tuple(q for q in USD_EQUIVALENT_QUOTES if q != UNIFIED_QUOTE)

_RECONNECT_DELAY_SECONDS = 5


class FxRates:
    """In-memory quote → USD rates, fed by watch_fx_rates()."""

    def __init__(self, max_age_seconds: float = FX_MAX_AGE_SECONDS, clock: Callable[[], float] = time.monotonic):
        self._max_age = max_age_seconds
        self._clock = clock
        self._rates: dict[str, tuple[Decimal, float]] = {}
        self._fallback_warned: set[str] = set()

    def update(self, quote: str, rate) -> Decimal:
        """Stores a live rate for `quote`. Raises ValueError for unknown quotes or non-positive rates."""
        quote = quote.upper()
        if quote not in CONVERTED_QUOTES:
            raise ValueError(f"Unsupported FX quote currency '{quote}'")
        value = to_decimal(rate)
        if value <= 0:
            raise ValueError(f"FX rate for {quote} must be positive, got {rate!r}")
        self._rates[quote] = (value, self._clock())
        self._fallback_warned.discard(quote)
        fx_rate_gauge.labels(quote=quote).set(float(value))
        return value

    def get(self, quote: str) -> tuple[Decimal, str]:
        """
        (rate, source) that converts a `quote`-denominated price to USD.
        source is "identity" for USD, "live" for a fresh rate, "peg" for the
        1:1 fallback. Raises ValueError for non-USD-equivalent quotes.
        """
        quote = quote.upper()
        if quote == UNIFIED_QUOTE:
            return PEG_RATE, RATE_SOURCE_IDENTITY
        if quote not in CONVERTED_QUOTES:
            raise ValueError(f"Unsupported quote currency '{quote}' — cannot convert to USD")

        entry = self._rates.get(quote)
        if entry is not None and self._clock() - entry[1] <= self._max_age:
            return entry[0], RATE_SOURCE_LIVE

        fx_rate_fallback_total.labels(quote=quote).inc()
        if quote not in self._fallback_warned:
            # Warn once per outage, not once per candle.
            self._fallback_warned.add(quote)
            logger.warning(f"No fresh {quote}/USD rate — converting at the 1:1 peg until one arrives")
        return PEG_RATE, RATE_SOURCE_PEG


def _ticker_rate(ticker: dict):
    """Best available price from a CCXT ticker: last trade, else bid/ask mid."""
    last = ticker.get("last") or ticker.get("close")
    if last:
        return last
    bid, ask = ticker.get("bid"), ticker.get("ask")
    if bid and ask:
        return (to_decimal(bid) + to_decimal(ask)) / 2
    return None


def _apply_ticker(rates: FxRates, quote: str, ticker: dict) -> None:
    rate = _ticker_rate(ticker or {})
    if rate is None:
        logger.warning(f"FX ticker for {quote}/USD has no price — ignoring")
        return
    rates.update(quote, rate)


async def _watch_quote(exchange, rates: FxRates, quote: str) -> None:
    symbol = f"{quote}/{UNIFIED_QUOTE}"
    _apply_ticker(rates, quote, await exchange.fetch_ticker(symbol))
    while True:
        _apply_ticker(rates, quote, await exchange.watch_ticker(symbol))


async def watch_fx_rates(
    rates: FxRates,
    exchange: Optional[object] = None,
    quotes: tuple[str, ...] = CONVERTED_QUOTES,
) -> None:
    """Keeps `rates` up to date from the reference exchange. Reconnects on errors."""
    if exchange is None:
        exchange = getattr(ccxtpro, FX_REFERENCE_EXCHANGE)({})
    exchange_id = getattr(exchange, "id", FX_REFERENCE_EXCHANGE)

    while True:
        try:
            await exchange.load_markets()
            markets = getattr(exchange, "markets", None) or {}
            available = [q for q in quotes if f"{q}/{UNIFIED_QUOTE}" in markets]
            missing = sorted(set(quotes) - set(available))
            if missing:
                logger.warning(f"[{exchange_id}] no FX market for {missing} — those quotes use the 1:1 peg")
            if not available:
                return
            logger.info(f"[{exchange_id}] watching FX rates for {available}")
            await run_all(_watch_quote(exchange, rates, q) for q in available)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[{exchange_id}] FX rate stream error: {e} — reconnecting in {_RECONNECT_DELAY_SECONDS}s")
            await asyncio.sleep(_RECONNECT_DELAY_SECONDS)
        finally:
            try:
                await exchange.close()
            except Exception:
                pass
