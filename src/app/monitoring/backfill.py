"""Resumable five-year daily backfill; never invent historical USD conversion."""

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import ccxt.async_support as ccxt
from sqlalchemy import select

from app import config
from app.fiat.rates import load_series
from app.helpers.currencies import rate_on
from app.helpers.prices import to_decimal
from app.helpers.time import utc_now_naive
from app.helpers.upsert import insert_ignore_duplicates
from app.models.candle_history import CandleHistory
from app.models.database import AsyncSessionLocal, engine
from app.models.monitoring import MonitoringHistoryEvent
from app.routers.market import resolve_ticker
from app.trading.quotes import resolve_source

logger = logging.getLogger(__name__)


async def crypto_rows(exchange_name: str, source_ticker: str, start: datetime,
                      end: datetime) -> tuple[list[list], list[datetime]]:
    client = getattr(ccxt, exchange_name)({"enableRateLimit": True, "timeout": 20000})
    rows = []
    cursor = int(start.replace(tzinfo=timezone.utc).timestamp() * 1000)
    stop = int(end.replace(tzinfo=timezone.utc).timestamp() * 1000)
    try:
        while cursor < stop:
            batch = await client.fetch_ohlcv(source_ticker, "1d", since=cursor, limit=500)
            if not batch:
                break
            rows.extend(row for row in batch if cursor <= row[0] < stop)
            next_cursor = max(row[0] for row in batch) + 86_400_000
            if next_cursor <= cursor:
                break
            cursor = next_cursor
        return rows, []
    finally:
        await client.close()


def stock_rows(symbol: str, start: datetime, end: datetime) -> tuple[list[list], list[datetime]]:
    import yfinance as yf
    frame = yf.Ticker(symbol).history(start=start.date().isoformat(), end=end.date().isoformat(),
                                      interval="1d", auto_adjust=False, actions=True)
    rows, splits = [], []
    for stamp, row in frame.iterrows():
        day = datetime(stamp.year, stamp.month, stamp.day)
        if row.get("Stock Splits", 0):
            splits.append(day)
        rows.append([int(day.replace(tzinfo=timezone.utc).timestamp() * 1000),
                     *[row[name] for name in ("Open", "High", "Low", "Close", "Volume")]])
    return rows, splits


async def backfill(exchange: str, ticker: str) -> dict:
    ticker = resolve_ticker(ticker)
    end = utc_now_naive().replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=5 * 365)
    async with AsyncSessionLocal() as db:
        source = await resolve_source(db, exchange, ticker)
        currency = source.source_ticker.split("/")[1]
        rows, splits = (await asyncio.to_thread(stock_rows, source.source_ticker.split("/")[0], start, end)
                        if source.asset_class == "stock"
                        else await crypto_rows(exchange, source.source_ticker, start, end))
        stable_rates = {}
        if currency in ("USDT", "USDC"):
            fx_rows, _ = await crypto_rows(config.FX_REFERENCE_EXCHANGE, f"{currency}/USD", start, end)
            stable_rates = {datetime.fromtimestamp(row[0]/1000, timezone.utc).date(): Decimal(str(row[4]))
                            for row in fx_rows}
        rates = (await load_series(db, currency, start.date(), end.date())
                 if currency not in ("USD", "USDT", "USDC") else [])
        for stamp in splits:
            await insert_ignore_duplicates(db, MonitoringHistoryEvent, [{
                "exchange": exchange, "ticker": ticker, "timestamp": stamp,
            }], ["exchange", "ticker", "timestamp"])
        await db.commit()
        # Resume safely: existing archive rows win. Never alter trading history.
        existing = set((await db.scalars(select(CandleHistory.timestamp).where(
            CandleHistory.exchange == exchange, CandleHistory.ticker == ticker,
            CandleHistory.interval == "1d", CandleHistory.timestamp >= start))).all())
        inserted = skipped = 0
        for raw in rows:
            stamp = datetime.fromtimestamp(raw[0] / 1000, timezone.utc).replace(tzinfo=None)
            if stamp >= end or stamp in existing:
                continue
            rate = Decimal(1)
            if currency in ("USDT", "USDC"):
                rate = stable_rates.get(stamp.date())
                if rate is None or not rate.is_finite() or rate <= 0:
                    skipped += 1
                    continue
            elif currency != "USD":
                entry = rate_on(rates, stamp.date())
                if entry is None or (stamp.date() - entry[0]).days > 7:
                    skipped += 1
                    continue
                rate = Decimal(1) / entry[1]
            prices = [to_decimal(Decimal(str(value)) * rate) for value in raw[1:5]]
            if any(not p.is_finite() or p <= 0 for p in prices):
                skipped += 1
                continue
            inserted += await insert_ignore_duplicates(db, CandleHistory, [{
                "exchange": exchange, "ticker": ticker, "interval": "1d", "timestamp": stamp,
                "trade_date": stamp.date(), "open_price": prices[0], "high_price": prices[1],
                "low_price": prices[2], "close_price": prices[3], "volume": to_decimal(raw[5]),
                "source_ticker": source.source_ticker, "quote_currency": "USD", "fx_rate": rate,
            }], ["exchange", "ticker", "interval", "timestamp"])
            # Per-row commit makes interrupted provider runs resumable.
            await db.commit()
        return {"inserted": inserted, "skipped_missing_conversion_or_invalid": skipped}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exchange")
    parser.add_argument("ticker")
    args = parser.parse_args()
    try:
        print(await backfill(args.exchange, args.ticker))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
