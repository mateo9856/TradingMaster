"""
EOD (End-of-Day) Archive Job

Runs as its own process (app/eod_runner.py, driven by cron or the eod-archive
CronJob), not from an in-process scheduler — a crashed or redeployed API must
not silently skip a day.

What it does:
  1. Reads the target day's candles from the hot `candles` table, in chunks
  2. Copies them into `candles_history` with ON CONFLICT DO NOTHING
  3. Exports that day's history to Parquet files (for backtesting / ML)
  4. Deletes candles past RETENTION_DAYS from the hot table — but only rows
     that are actually present in history
  5. Records the outcome in `job_runs`

**Re-running a day is safe.** The archive insert ignores rows history already
has, so a manual re-run, a CronJob `backoffLimit` retry, and the local
overlay's every-10-minutes schedule are all no-ops after the first success.
Before the unique key on candles_history existed, each of those appended a
second full copy of the day.

Use `replace=True` to genuinely re-archive a day after correcting source data:
that deletes the day's history rows first, then re-inserts them.

File structure of Parquet exports (one file per exchange + unified ticker +
day, all intervals in it — filter on the `interval` column):
  data/
    binance/
      BTC-USD/
        2026-09-05.parquet

Run manually:
    python -m app.eod_runner 2026-09-05
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.helpers.prices import PRICE_SCALE
from app.helpers.time import utc_now_naive
from app.helpers.upsert import insert_ignore_duplicates
from app.metrics import (
    eod_job_duration_seconds,
    eod_job_runs_total,
    eod_parquet_files_written_total,
    eod_parquet_skipped_total,
    eod_rows_archived_total,
    eod_rows_deleted_total,
    eod_rows_skipped_duplicate_total,
)
from app.models.candle import Candle
from app.models.candle_history import CandleHistory
from app.models.database import AsyncSessionLocal
from app.models.job_run import (
    EOD_ARCHIVE_JOB,
    STATUS_FAILURE,
    STATUS_REFUSED,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    JobRun,
)

logger = logging.getLogger(__name__)

# How many days to keep in the hot candles table
RETENTION_DAYS: int = 7

# Where to write Parquet exports
PARQUET_BASE_DIR = Path(os.getenv("PARQUET_BASE_DIR", "data"))

# Rows per archive batch. The job used to load a whole day as ORM objects in
# one go — ~230k rows at current market coverage, and growing with every market
# added through the API.
CHUNK_SIZE: int = 5_000

# Exact-decimal columns in the Parquet export
DECIMAL_COLUMNS = ("open_price", "high_price", "low_price", "close_price", "volume", "fx_rate")

# candles_history's natural key — what the archive insert resolves conflicts on.
HISTORY_KEY = ("exchange", "ticker", "interval", "timestamp")

# Advisory-lock key for the whole job. Arbitrary but fixed; PostgreSQL only.
ADVISORY_LOCK_KEY: int = 8_531_907_442


class ArchiveLockedError(RuntimeError):
    """Another archive run holds the advisory lock."""


class NothingToReplaceError(RuntimeError):
    """--replace was asked for a day whose source candles are already gone."""


@dataclass(frozen=True)
class ArchiveResult:
    """Outcome of one archive run, also written to job_runs."""
    target_date: date
    inserted: int = 0
    skipped_duplicate: int = 0
    deleted: int = 0
    files_written: int = 0

    @property
    def total_seen(self) -> int:
        return self.inserted + self.skipped_duplicate


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    """[start, end] of the day, inclusive of the final microsecond."""
    return (
        datetime.combine(target_date, datetime.min.time()),
        datetime.combine(target_date, datetime.max.time()),
    )


@asynccontextmanager
async def _advisory_lock(bind: AsyncEngine | None) -> AsyncIterator[bool]:
    """
    Hold the job's advisory lock for the whole run, so two runs can't archive
    concurrently.

    The CronJob's concurrencyPolicy: Forbid covers the scheduled path only —
    the API's POST /history/archive/{date} could be fired repeatedly and each
    call started its own full run.

    The lock lives on a **dedicated connection** from the same engine, not on
    the working session: a PostgreSQL advisory lock belongs to the connection
    that took it, and the archive session commits after every chunk, which
    hands its connection back to the pool and would drop the lock.

    `bind` is taken from the running session rather than imported, so the lock
    is always on the database the job is actually working against.

    Yields True when the lock is held. Always True on SQLite, which has no
    advisory locks and no concurrent archive runs to worry about.
    """
    if bind is None or bind.dialect.name != "postgresql":
        yield True
        return

    connection = await bind.connect()
    acquired = False
    try:
        acquired = bool(await connection.scalar(select(func.pg_try_advisory_lock(ADVISORY_LOCK_KEY))))
        yield acquired
    finally:
        if acquired:
            await connection.scalar(select(func.pg_advisory_unlock(ADVISORY_LOCK_KEY)))
        await connection.close()


async def _delete_history_for(db: AsyncSession, target_date: date) -> int:
    """
    Drop a day's archived rows so they can be re-archived — the `replace=True`
    path — but only rows the hot table can still reproduce.

    Retention deletes hot candles once they are archived, so by the time anyone
    reaches for --replace the source rows are usually gone. Deleting the whole
    day unconditionally would then wipe the archive and re-insert nothing,
    which is the opposite of what --replace is for. Instead:

      * refuse outright when the day has no source candles left, and
      * otherwise delete only the rows that have a matching source candle,
        leaving anything unreproducible in place.
    """
    start, end = _day_bounds(target_date)

    source_count = await db.scalar(
        select(func.count())
        .select_from(Candle)
        .where(Candle.timestamp >= start)
        .where(Candle.timestamp <= end)
    ) or 0

    if source_count == 0:
        raise NothingToReplaceError(
            f"Refusing to replace {target_date}: the hot candles table has no rows for that "
            "day, so its history could be deleted but not rebuilt. Re-ingest the day first, "
            "or leave the existing archive alone."
        )

    reproducible = (
        select(Candle.id)
        .where(Candle.exchange == CandleHistory.exchange)
        .where(Candle.ticker == CandleHistory.ticker)
        .where(Candle.interval == CandleHistory.interval)
        .where(Candle.timestamp == CandleHistory.timestamp)
    )

    result = await db.execute(
        delete(CandleHistory)
        .where(CandleHistory.trade_date == target_date)
        .where(exists(reproducible))
    )
    await db.commit()
    deleted = max(result.rowcount, 0)
    logger.info(
        f"Removed {deleted} reproducible history row(s) for {target_date} (replace mode); "
        f"{source_count} source candle(s) will be re-archived"
    )
    return deleted


async def _archive_date(db: AsyncSession, target_date: date) -> tuple[int, int]:
    """
    Copy the day's candles from `candles` into `candles_history`, skipping any
    history already holds. Returns (inserted, skipped_duplicate).

    Streams in CHUNK_SIZE batches and commits each one: a day is far too large
    to hold in memory, and a partial archive is not a problem because re-running
    resumes harmlessly.
    """
    start, end = _day_bounds(target_date)

    statement = (
        select(Candle)
        .where(Candle.timestamp >= start)
        .where(Candle.timestamp <= end)
        .order_by(Candle.timestamp)
        .execution_options(yield_per=CHUNK_SIZE)
    )

    inserted = skipped = 0
    batch: list[dict] = []

    async def flush() -> None:
        nonlocal inserted, skipped, batch
        if not batch:
            return
        written = await insert_ignore_duplicates(db, CandleHistory, batch, HISTORY_KEY)
        await db.commit()
        inserted += written
        skipped += len(batch) - written
        batch = []

    result = await db.stream(statement)
    async for candle in result.scalars():
        batch.append({
            "exchange":       candle.exchange,
            "ticker":         candle.ticker,
            "interval":       candle.interval,
            "trade_date":     target_date,
            "timestamp":      candle.timestamp,
            "open_price":     candle.open_price,
            "high_price":     candle.high_price,
            "low_price":      candle.low_price,
            "close_price":    candle.close_price,
            "volume":         candle.volume,
            "source_ticker":  candle.source_ticker,
            "quote_currency": candle.quote_currency,
            "fx_rate":        candle.fx_rate,
            "archived_at":    utc_now_naive(),
        })
        if len(batch) >= CHUNK_SIZE:
            await flush()
    await flush()

    if inserted == 0 and skipped == 0:
        logger.info(f"No candles found for {target_date} — nothing to archive")
    else:
        logger.info(
            f"Archived {inserted} candle(s) for {target_date} "
            f"({skipped} already in history)"
        )
    return inserted, skipped


async def _export_parquet(db: AsyncSession, target_date: date) -> int:
    """
    Export candles_history for target_date to Parquet, one file per
    exchange+ticker. Prices are written as exact decimals (decimal128), not
    floats. Returns the number of files written.

    Driven by what history holds rather than by what this run inserted, so
    re-archiving a day whose hot candles were already cleaned up still produces
    the file. Each file is written to a temporary path and moved into place, so
    a crash mid-write cannot leave a truncated archive behind.
    """
    try:
        import pandas as pd
        import pyarrow.parquet as pq
    except ImportError:
        logger.warning("pandas/pyarrow not installed — skipping Parquet export. Run: pip install pandas pyarrow")
        eod_parquet_skipped_total.inc()
        return 0

    result = await db.execute(
        select(CandleHistory)
        .where(CandleHistory.trade_date == target_date)
        .order_by(CandleHistory.exchange, CandleHistory.ticker, CandleHistory.timestamp)
    )
    rows = result.scalars().all()

    if not rows:
        return 0

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

    files_written = 0
    for (exchange, ticker), group in df.groupby(["exchange", "ticker"]):
        safe_ticker = ticker.replace("/", "-")
        out_dir = PARQUET_BASE_DIR / exchange / safe_ticker
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{target_date}.parquet"
        tmp_path = out_path.with_suffix(".parquet.tmp")

        pq.write_table(_to_arrow(group.drop(columns=["exchange", "ticker"])), tmp_path)
        os.replace(tmp_path, out_path)      # atomic within the same filesystem

        files_written += 1
        eod_parquet_files_written_total.inc()
        logger.info(f"Exported Parquet: {out_path} ({len(group)} rows)")

    return files_written


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
    Delete candles past RETENTION_DAYS from the hot table — but only rows that
    are present in candles_history.

    The EXISTS guard is the point: this used to delete purely by wall clock, so
    a day whose archive had failed was still destroyed on schedule, silently
    and permanently. Now unarchived candles survive until an archive run has
    actually captured them.
    """
    cutoff = utc_now_naive() - timedelta(days=RETENTION_DAYS)

    archived = (
        select(CandleHistory.id)
        .where(CandleHistory.exchange == Candle.exchange)
        .where(CandleHistory.ticker == Candle.ticker)
        .where(CandleHistory.interval == Candle.interval)
        .where(CandleHistory.timestamp == Candle.timestamp)
    )

    result = await db.execute(
        delete(Candle).where(Candle.timestamp < cutoff).where(exists(archived))
    )
    await db.commit()
    deleted = max(result.rowcount, 0)
    logger.info(f"Cleaned up {deleted} archived candle(s) older than {RETENTION_DAYS} days")
    return deleted


async def _start_run(db: AsyncSession, target_date: date) -> JobRun:
    run = JobRun(
        job_name=EOD_ARCHIVE_JOB,
        target_date=target_date,
        started_at=utc_now_naive(),
        status=STATUS_RUNNING,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def _finish_run(
    db: AsyncSession,
    run: JobRun,
    status: str,
    result: ArchiveResult | None = None,
    error: str | None = None,
) -> None:
    run.finished_at = utc_now_naive()
    run.status = status
    run.error = error
    if result is not None:
        run.rows_archived = result.inserted
        run.rows_skipped = result.skipped_duplicate
        run.rows_deleted = result.deleted
        run.files_written = result.files_written
    db.add(run)
    await db.commit()


async def run_eod_job(
    target_date: date | None = None,
    *,
    replace: bool = False,
    dry_run: bool = False,
) -> ArchiveResult:
    """
    Archive one day. Defaults to yesterday (UTC).

    replace  — delete the day's existing history rows first and re-archive it.
               Only for correcting bad data; a plain re-run is already safe.
    dry_run  — report what would be archived, change nothing.

    Raises ArchiveLockedError when another run holds the advisory lock.
    """
    if target_date is None:
        target_date = (utc_now_naive() - timedelta(days=1)).date()

    mode = " (dry run)" if dry_run else " (replace)" if replace else ""
    logger.info(f"Starting EOD archive job for {target_date}{mode}...")

    start = time.perf_counter()
    result = ArchiveResult(target_date=target_date)

    try:
        async with AsyncSessionLocal() as db, _advisory_lock(db.bind) as locked:
            if not locked:
                raise ArchiveLockedError(
                    "Another EOD archive run is already in progress — this one will not start."
                )

            if dry_run:
                result = await _describe_pending(db, target_date)
                logger.info(
                    f"Dry run for {target_date}: {result.total_seen} candle(s) in the hot "
                    f"table, {result.skipped_duplicate} already archived"
                )
                eod_job_runs_total.labels(status="success").inc()
                return result

            run = await _start_run(db, target_date)
            try:
                if replace:
                    await _delete_history_for(db, target_date)

                inserted, skipped = await _archive_date(db, target_date)
                files = await _export_parquet(db, target_date)
                deleted = await _cleanup_old_candles(db)

                result = ArchiveResult(
                    target_date=target_date,
                    inserted=inserted,
                    skipped_duplicate=skipped,
                    deleted=deleted,
                    files_written=files,
                )
                await _finish_run(db, run, STATUS_SUCCESS, result)
            except NothingToReplaceError as error:
                # A rejected request, not a broken job — recorded separately so
                # it doesn't raise the "archive failed" alert.
                await _finish_run(db, run, STATUS_REFUSED, error=str(error))
                raise
            except Exception as error:
                await _finish_run(db, run, STATUS_FAILURE, error=repr(error))
                raise

        eod_rows_archived_total.inc(result.inserted)
        eod_rows_skipped_duplicate_total.inc(result.skipped_duplicate)
        eod_rows_deleted_total.inc(result.deleted)
        eod_job_runs_total.labels(status="success").inc()

    except (ArchiveLockedError, NothingToReplaceError):
        # Neither is a job failure: one means another run is doing the work,
        # the other means the request was rejected without touching anything.
        eod_job_runs_total.labels(status="skipped").inc()
        raise
    except Exception:
        eod_job_runs_total.labels(status="failure").inc()
        raise
    finally:
        eod_job_duration_seconds.observe(time.perf_counter() - start)

    logger.info(
        f"EOD archive job complete for {target_date} — "
        f"{result.inserted} archived, {result.skipped_duplicate} already present, "
        f"{result.files_written} file(s), {result.deleted} cleaned up"
    )
    return result


async def _describe_pending(db: AsyncSession, target_date: date) -> ArchiveResult:
    """Count what a real run would do, without writing anything (--dry-run)."""
    start, end = _day_bounds(target_date)

    total = await db.scalar(
        select(func.count())
        .select_from(Candle)
        .where(Candle.timestamp >= start)
        .where(Candle.timestamp <= end)
    ) or 0

    already = await db.scalar(
        select(func.count())
        .select_from(CandleHistory)
        .where(CandleHistory.trade_date == target_date)
    ) or 0

    return ArchiveResult(
        target_date=target_date,
        inserted=max(total - already, 0),
        skipped_duplicate=min(already, total),
    )
