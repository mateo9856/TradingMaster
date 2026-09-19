"""
EOD (End-of-Day) Archive Job

Runs once at midnight (configurable via APScheduler in main.py).

What it does:
  1. Reads all candles from yesterday from the `candles` table
  2. Copies them to `candles_history` (cold storage, partitioned by date)
  3. Exports them to Parquet files on disk (for backtesting / ML)
  4. Deletes candles older than RETENTION_DAYS from the hot `candles` table

File structure of Parquet exports (one file per exchange + unified ticker +
day, all intervals in it — filter on the `interval` column):
  data/
    binance/
      BTC-USD/
        2026-09-05.parquet
    kraken/
      BTC-USD/
        2026-09-05.parquet

Run manually:
    python -c "import asyncio; from app.jobs.eod_archive import run_eod_job; asyncio.run(run_eod_job())"
"""

import logging
import time
from datetime import datetime, timedelta, date
from pathlib import Path

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import eod_job_duration_seconds, eod_job_runs_total
from app.models.candle import Candle
from app.models.candle_history import CandleHistory
from app.models.database import AsyncSessionLocal
from app.helpers.prices import PRICE_SCALE
from app.helpers.time import utc_now_naive

logger = logging.getLogger(__name__)

# How many days to keep in the hot candles table
RETENTION_DAYS: int = 7

# Where to write Parquet exports
PARQUET_BASE_DIR = Path("data")

# Exact-decimal columns in the Parquet export
DECIMAL_COLUMNS = ("open_price", "high_price", "low_price", "close_price", "volume", "fx_rate")


async def _archive_date(db: AsyncSession, target_date: date) -> int:
    """
    Copies all candles for target_date from candles → candles_history.
    Returns the number of rows archived.
    """
    start = datetime.combine(target_date, datetime.min.time())
    end   = datetime.combine(target_date, datetime.max.time())

    result = await db.execute(
        select(Candle)
        .where(Candle.timestamp >= start)
        .where(Candle.timestamp <= end)
        .order_by(Candle.timestamp)
    )
    candles = result.scalars().all()

    if not candles:
        logger.info(f"No candles found for {target_date} — skipping archive")
        return 0

    # Insert into history table
    history_rows = [
        CandleHistory(
            exchange    = c.exchange,
            ticker      = c.ticker,
            interval    = c.interval,
            trade_date  = target_date,
            timestamp   = c.timestamp,
            open_price  = c.open_price,
            high_price  = c.high_price,
            low_price   = c.low_price,
            close_price = c.close_price,
            volume      = c.volume,
            source_ticker  = c.source_ticker,
            quote_currency = c.quote_currency,
            fx_rate        = c.fx_rate,
        )
        for c in candles
    ]
    db.add_all(history_rows)
    await db.commit()

    logger.info(f"Archived {len(history_rows)} candles for {target_date}")
    return len(history_rows)


async def _export_parquet(db: AsyncSession, target_date: date) -> None:
    """
    Exports candles_history for target_date to Parquet files.
    Groups by exchange and ticker for efficient file layout. Prices are
    written as exact decimals (Parquet decimal128), not floats.
    """
    try:
        import pandas as pd
        import pyarrow.parquet as pq
    except ImportError:
        logger.warning("pandas not installed — skipping Parquet export. Run: pip install pandas pyarrow")
        return

    result = await db.execute(
        select(CandleHistory)
        .where(CandleHistory.trade_date == target_date)
        .order_by(CandleHistory.exchange, CandleHistory.ticker, CandleHistory.timestamp)
    )
    rows = result.scalars().all()

    if not rows:
        return

    df = pd.DataFrame([{
        "exchange":    r.exchange,
        "ticker":      r.ticker,
        "interval":    r.interval,
        "timestamp":   r.timestamp,
        "open_price":  r.open_price,
        "high_price":  r.high_price,
        "low_price":   r.low_price,
        "close_price": r.close_price,
        "volume":      r.volume,
        "source_ticker":  r.source_ticker,
        "quote_currency": r.quote_currency,
        "fx_rate":        r.fx_rate,
    } for r in rows])

    # Write one Parquet file per exchange+ticker combination
    for (exchange, ticker), group in df.groupby(["exchange", "ticker"]):
        safe_ticker = ticker.replace("/", "-")
        out_dir = PARQUET_BASE_DIR / exchange / safe_ticker
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{target_date}.parquet"

        pq.write_table(_to_arrow(group.drop(columns=["exchange", "ticker"])), out_path)
        logger.info(f"Exported Parquet: {out_path} ({len(group)} rows)")


def _to_arrow(frame):
    """
    DataFrame → Arrow table with every price column pinned to decimal128(28, 8)
    (matching NUMERIC(28, 8) in the database), so all files share one schema
    instead of a precision inferred from each file's values.
    """
    import pyarrow as pa

    table = pa.Table.from_pandas(frame, preserve_index=False)
    decimal = pa.decimal128(28, PRICE_SCALE)
    schema = pa.schema([
        field.with_type(decimal) if field.name in DECIMAL_COLUMNS else field
        for field in table.schema
    ])
    return table.cast(schema)


async def _cleanup_old_candles(db: AsyncSession) -> int:
    """
    Deletes candles older than RETENTION_DAYS from the hot candles table.
    Returns number of deleted rows.
    """
    cutoff = utc_now_naive() - timedelta(days=RETENTION_DAYS)
    result = await db.execute(
        delete(Candle).where(Candle.timestamp < cutoff)
    )
    await db.commit()
    deleted = result.rowcount
    logger.info(f"Cleaned up {deleted} candles older than {RETENTION_DAYS} days")
    return deleted


async def run_eod_job(target_date: date | None = None) -> None:
    """
    Main EOD job entry point.
    By default archives yesterday's candles.
    Pass target_date to backfill a specific date.
    """
    if target_date is None:
        target_date = (utc_now_naive() - timedelta(days=1)).date()

    logger.info(f"Starting EOD archive job for {target_date}...")

    start = time.perf_counter()
    try:
        async with AsyncSessionLocal() as db:
            archived = await _archive_date(db, target_date)
            if archived > 0:
                await _export_parquet(db, target_date)
            await _cleanup_old_candles(db)
        eod_job_runs_total.labels(status="success").inc()
    except Exception:
        eod_job_runs_total.labels(status="failure").inc()
        raise
    finally:
        eod_job_duration_seconds.observe(time.perf_counter() - start)

    logger.info(f"EOD archive job complete for {target_date}")
