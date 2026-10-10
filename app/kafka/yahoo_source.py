"""
Yahoo Finance → unified feed: company stocks, polled.

Yahoo has no streaming API, so bars are polled with `yfinance` (an unofficial
client of Yahoo's public chart endpoint — no API key) and handed to the same
`_send_candle` every crypto exchange uses. A stock candle is therefore
indistinguishable from a crypto one downstream: unified `BASE/USD` ticker,
8-decimal USD strings, same Kafka topic scheme (yahoo.PKNWAUSD.candles), same
Flink job.

  - Symbols are Yahoo's own, with the listing venue as a suffix: AAPL (US),
    PKN.WA (Warsaw), SAP.DE (Xetra), EQNR.OL (Oslo). The `symbols` row carries
    the trading currency as its quote (PKN.WA/PLN), and the producer converts
    fiat quotes to USD with the ECB rate for the bar's date.
  - Quotes are delayed (~15 minutes, exchange licensing) and only move during
    trading hours. Yahoo's smallest bar is 1 minute, so there is no 30s.
  - A bar is re-sent while it is still forming (its values change between
    polls). The Flink sink upserts on (exchange, ticker, interval, timestamp),
    so the stored row ends up as the final bar — same as an in-progress
    watch_ohlcv candle. An unchanged bar is not sent again.
"""

import asyncio
import logging
import math
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from app.config import YAHOO_POLL_SECONDS
from app.helpers.intervals import interval_to_ms
from app.helpers.markets import split_symbol
from app.helpers.sources import POLL_INTERVALS
from app.metrics import stock_poll_errors_total

logger = logging.getLogger(__name__)

SOURCE_NAME = "yahoo"

# Unified interval → Yahoo interval.
YAHOO_INTERVALS: dict[str, str] = {"1m": "1m", "5m": "5m", "1h": "60m", "1d": "1d"}

# How far back each request looks. The first poll backfills this much so a
# chart has something to show; later polls only send what changed. Yahoo
# serves 1m bars for at most the last 7 days.
YAHOO_PERIODS: dict[str, str] = {"1m": "1d", "5m": "5d", "1h": "5d", "1d": "1mo"}

# Yahoo's prices carry float32 noise (331.79 arrives as 331.7900085449219).
# No stock market quotes finer than 0.0001, so rounding there restores the
# exchange's price instead of storing the noise at 8 decimals.
PRICE_DECIMALS = 4

# Longer bars don't need polling every minute: a 1h bar is re-read every 5 minutes.
_MAX_POLL_GAP_SECONDS = 300

SendCandle = Callable[[str, str, str, list], Awaitable[None]]   # (exchange, symbol, interval, ohlcv)


def poll_every(interval: str, poll_seconds: float = YAHOO_POLL_SECONDS) -> float:
    """Seconds between polls for `interval`: every poll for 1m, at most every 5 min for longer bars."""
    return max(poll_seconds, min(interval_to_ms(interval) / 1000, _MAX_POLL_GAP_SECONDS))


def download(yahoo_symbols: list[str], interval: str):
    """One batched Yahoo request (blocking — run it in a thread)."""
    import yfinance as yf   # imported here so the API and tests don't need it loaded

    return yf.download(
        tickers=yahoo_symbols,
        period=YAHOO_PERIODS[interval],
        interval=YAHOO_INTERVALS[interval],
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=False,
    )


def frame_for(frame, yahoo_symbol: str):
    """The OHLCV columns of one symbol from a (possibly multi-symbol) yf.download result, or None."""
    if frame is None or getattr(frame, "empty", True):
        return None
    columns = frame.columns
    if getattr(columns, "nlevels", 1) > 1:
        if yahoo_symbol not in columns.get_level_values(0):
            return None
        return frame[yahoo_symbol]
    return frame


def _bar_start_ms(ts, interval: str) -> int:
    """
    Bar start in ms since epoch (UTC). Daily bars come back as local midnight
    of the exchange (00:00+02:00 in Warsaw = 22:00 UTC the day before); they
    are stored at 00:00 UTC of the trading date instead, matching how every
    other 1d candle in the feed is keyed.
    """
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    if interval == "1d":
        return int(datetime(ts.year, ts.month, ts.day, tzinfo=timezone.utc).timestamp() * 1000)
    return int(ts.tz_convert("UTC").timestamp() * 1000)


def _number(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def rows_to_ohlcv(frame, interval: str) -> list[list]:
    """[[ts_ms, open, high, low, close, volume], ...] — rows without a full price set are dropped."""
    if frame is None:
        return []
    rows = []
    for ts, row in frame.iterrows():
        prices = [_number(row.get(column)) for column in ("Open", "High", "Low", "Close")]
        if any(p is None for p in prices):
            continue      # the other market's hours in a mixed batch, or a halted stock
        prices = [round(p, PRICE_DECIMALS) for p in prices]
        volume = _number(row.get("Volume")) or 0.0
        rows.append([_bar_start_ms(ts, interval), *prices, volume])
    return rows


class YahooPoller:
    """Polls Yahoo for every configured symbol and interval, sending new or changed bars."""

    def __init__(
        self,
        symbols: dict[str, list[str]],
        send: SendCandle,
        fetch: Callable[[list[str], str], object] = download,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._symbols = symbols                           # "PKN.WA/PLN" → ["1m", "5m", ...]
        self._send = send
        self._fetch = fetch
        self._clock = clock
        self._next_poll: dict[str, float] = {}
        self._last_sent: dict[tuple[str, str], list] = {}  # (symbol, interval) → last bar sent

    def _symbols_for(self, interval: str) -> dict[str, str]:
        """{yahoo symbol: configured market} for the markets collected at `interval`."""
        return {
            split_symbol(market)[0]: market
            for market, intervals in self._symbols.items()
            if interval in intervals
        }

    async def poll_interval(self, interval: str) -> int:
        """Fetches one interval for every symbol and sends what's new. Returns bars sent."""
        wanted = self._symbols_for(interval)
        if not wanted:
            return 0
        frame = await asyncio.to_thread(self._fetch, list(wanted), interval)

        sent = 0
        for yahoo_symbol, market in wanted.items():
            last = self._last_sent.get((market, interval))
            for bar in rows_to_ohlcv(frame_for(frame, yahoo_symbol), interval):
                if last is not None and (bar[0] < last[0] or bar == last):
                    continue
                await self._send(SOURCE_NAME, market, interval, bar)
                last = bar
                sent += 1
            if last is not None:
                self._last_sent[(market, interval)] = last
        return sent

    async def poll_due(self) -> None:
        """Polls every interval whose turn has come. One failing interval doesn't stop the others."""
        now = self._clock()
        for interval in POLL_INTERVALS:
            if now < self._next_poll.get(interval, 0):
                continue
            self._next_poll[interval] = now + poll_every(interval)
            try:
                sent = await self.poll_interval(interval)
                logger.debug(f"[{SOURCE_NAME}] {interval}: sent {sent} bar(s)")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                stock_poll_errors_total.labels(source=SOURCE_NAME).inc()
                logger.warning(f"[{SOURCE_NAME}] {interval} poll failed: {e}")


async def stream_yahoo(exc_config: dict, send: SendCandle, poll_seconds: float = YAHOO_POLL_SECONDS) -> None:
    """Runs until cancelled — the producer's stream task for the `yahoo` exchange."""
    symbols = exc_config["symbols"]
    unsupported = {m: [i for i in ivs if i not in YAHOO_INTERVALS] for m, ivs in symbols.items()}
    for market, intervals in unsupported.items():
        if intervals:
            logger.warning(f"[{SOURCE_NAME}] {market}: Yahoo has no {intervals} bars — skipping those")
    logger.info(f"[{SOURCE_NAME}] polling {len(symbols)} stock(s) every {poll_seconds}s")

    poller = YahooPoller(symbols, send)
    while True:
        await poller.poll_due()
        await asyncio.sleep(poll_seconds)
