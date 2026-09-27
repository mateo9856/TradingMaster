"""
EOD archive job.

The archive and cleanup steps are exercised against a real (SQLite) session
rather than a mocked one. Their correctness now lives in SQL — ON CONFLICT DO
NOTHING for the insert, an EXISTS sub-query for the cleanup — and a MagicMock
session can only assert that some statement was built, not that it does the
right thing. The Parquet tests stay mock-driven; they only need rows in, files
out.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import func, select

from app.jobs import eod_archive
from app.models.candle import Candle
from app.models.candle_history import CandleHistory

TARGET_DATE = date(2026, 6, 23)


def make_candle(timestamp=datetime(2026, 6, 23, 12, 0), **overrides):
    values = dict(
        exchange="binance", ticker="BTC/USD", interval="1m",
        timestamp=timestamp, open_price=Decimal("10.12345678"), high_price=12,
        low_price=9, close_price=Decimal("11.00000001"), volume=5,
        source_ticker="BTC/USDT", quote_currency="USD", fx_rate=Decimal("0.99980000"),
    )
    values.update(overrides)
    return Candle(**values)


def query_result(rows):
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


async def _history_count(db) -> int:
    return await db.scalar(select(func.count()).select_from(CandleHistory))


# ── Archiving ────────────────────────────────────────────────────────────────

async def test_archive_date_copies_candles_to_history(db_session):
    db_session.add(make_candle())
    await db_session.commit()

    inserted, skipped = await eod_archive._archive_date(db_session, TARGET_DATE)

    assert (inserted, skipped) == (1, 0)
    row = (await db_session.execute(select(CandleHistory))).scalars().one()
    assert row.exchange == "binance"
    assert row.ticker == "BTC/USD"
    assert row.trade_date == TARGET_DATE
    assert row.close_price == Decimal("11.00000001")
    assert row.source_ticker == "BTC/USDT"
    assert row.quote_currency == "USD"
    assert row.fx_rate == Decimal("0.99980000")


async def test_archive_date_is_a_no_op_when_there_are_no_candles(db_session):
    assert await eod_archive._archive_date(db_session, TARGET_DATE) == (0, 0)
    assert await _history_count(db_session) == 0


async def test_archiving_the_same_day_twice_does_not_duplicate_it(db_session):
    """
    The whole point of the change: a re-run, a CronJob backoffLimit retry, and
    the local overlay's every-10-minutes schedule must all be no-ops rather
    than appending a second copy of the day.
    """
    db_session.add_all([
        make_candle(datetime(2026, 6, 23, 12, 0)),
        make_candle(datetime(2026, 6, 23, 12, 1)),
    ])
    await db_session.commit()

    assert await eod_archive._archive_date(db_session, TARGET_DATE) == (2, 0)
    assert await _history_count(db_session) == 2

    # Second run: everything is already there.
    assert await eod_archive._archive_date(db_session, TARGET_DATE) == (0, 2)
    assert await _history_count(db_session) == 2


async def test_archive_date_inserts_only_the_candles_missing_from_history(db_session):
    db_session.add(make_candle(datetime(2026, 6, 23, 12, 0)))
    await db_session.commit()
    await eod_archive._archive_date(db_session, TARGET_DATE)

    # A candle that arrived after the first archive run.
    db_session.add(make_candle(datetime(2026, 6, 23, 12, 5)))
    await db_session.commit()

    assert await eod_archive._archive_date(db_session, TARGET_DATE) == (1, 1)
    assert await _history_count(db_session) == 2


async def test_archive_date_spans_the_whole_day_inclusive(db_session):
    db_session.add_all([
        make_candle(datetime(2026, 6, 23, 0, 0, 0)),
        make_candle(datetime(2026, 6, 23, 23, 59, 59)),
        make_candle(datetime(2026, 6, 24, 0, 0, 0)),     # next day — excluded
    ])
    await db_session.commit()

    inserted, _ = await eod_archive._archive_date(db_session, TARGET_DATE)
    assert inserted == 2


async def test_archive_date_commits_in_chunks(db_session):
    """A day is far too large to hold in memory as ORM objects."""
    db_session.add_all([
        make_candle(datetime(2026, 6, 23, 0, 0) + timedelta(minutes=i)) for i in range(7)
    ])
    await db_session.commit()

    with patch.object(eod_archive, "CHUNK_SIZE", 3):
        inserted, skipped = await eod_archive._archive_date(db_session, TARGET_DATE)

    assert (inserted, skipped) == (7, 0)
    assert await _history_count(db_session) == 7


# ── Retention cleanup ────────────────────────────────────────────────────────

async def test_cleanup_deletes_only_candles_that_reached_history(db_session):
    """
    Cleanup used to delete purely by wall clock, so a day whose archive had
    failed was still destroyed on schedule — silently and permanently.
    """
    old = eod_archive.utc_now_naive() - timedelta(days=eod_archive.RETENTION_DAYS + 3)
    archived = make_candle(old, ticker="BTC/USD")
    unarchived = make_candle(old, ticker="ETH/USD")
    db_session.add_all([archived, unarchived])
    await db_session.commit()

    # Only BTC made it into history.
    db_session.add(CandleHistory(
        exchange="binance", ticker="BTC/USD", interval="1m",
        trade_date=old.date(), timestamp=old,
        open_price=1, high_price=1, low_price=1, close_price=1, volume=1,
    ))
    await db_session.commit()

    deleted = await eod_archive._cleanup_old_candles(db_session)

    assert deleted == 1
    remaining = (await db_session.execute(select(Candle.ticker))).scalars().all()
    assert remaining == ["ETH/USD"]


async def test_cleanup_leaves_candles_inside_the_retention_window(db_session):
    recent = eod_archive.utc_now_naive() - timedelta(days=1)
    db_session.add(make_candle(recent))
    await db_session.commit()
    db_session.add(CandleHistory(
        exchange="binance", ticker="BTC/USD", interval="1m",
        trade_date=recent.date(), timestamp=recent,
        open_price=1, high_price=1, low_price=1, close_price=1, volume=1,
    ))
    await db_session.commit()

    assert await eod_archive._cleanup_old_candles(db_session) == 0
    assert await db_session.scalar(select(func.count()).select_from(Candle)) == 1


# ── Parquet export ───────────────────────────────────────────────────────────

async def test_export_parquet_groups_by_exchange_and_ticker(tmp_path):
    rows = [
        MagicMock(exchange="binance", ticker="BTC/USD", interval="1m",
                  timestamp=datetime(2026, 6, 23, 12), open_price=Decimal("10.00000000"),
                  high_price=Decimal("12.00000000"), low_price=Decimal("9.00000000"),
                  close_price=Decimal("11.12345678"), volume=Decimal("5.00000000"),
                  source_ticker="BTC/USDT", quote_currency="USD", fx_rate=Decimal("0.99980000")),
        MagicMock(exchange="kraken", ticker="ETH/USD", interval="1m",
                  timestamp=datetime(2026, 6, 23, 12), open_price=Decimal("20.00000000"),
                  high_price=Decimal("22.00000000"), low_price=Decimal("19.00000000"),
                  close_price=Decimal("21.00000000"), volume=Decimal("7.00000000"),
                  source_ticker=None, quote_currency="USD", fx_rate=None),
    ]
    db = AsyncMock()
    db.execute.return_value = query_result(rows)

    with patch.object(eod_archive, "PARQUET_BASE_DIR", tmp_path):
        files_written = await eod_archive._export_parquet(db, TARGET_DATE)

    assert files_written == 2
    exported = tmp_path / "binance" / "BTC-USD" / "2026-06-23.parquet"
    assert exported.exists()
    frame = pd.read_parquet(exported)
    assert list(frame["close_price"]) == [Decimal("11.12345678")]
    assert list(frame["source_ticker"]) == ["BTC/USDT"]
    assert "exchange" not in frame.columns
    assert "ticker" not in frame.columns


async def test_export_parquet_pins_exact_decimal_schema_in_every_file(tmp_path):
    rows = [
        MagicMock(exchange=exchange, ticker="BTC/USD", interval="1m",
                  timestamp=datetime(2026, 6, 23, 12), open_price=price, high_price=price,
                  low_price=price, close_price=price, volume=Decimal("0.00000001"),
                  source_ticker="BTC/USD", quote_currency="USD", fx_rate=None)
        for exchange, price in (("binance", Decimal("1.50000000")), ("kraken", Decimal("65000.10000000")))
    ]
    db = AsyncMock()
    db.execute.return_value = query_result(rows)

    with patch.object(eod_archive, "PARQUET_BASE_DIR", tmp_path):
        await eod_archive._export_parquet(db, TARGET_DATE)

    schemas = [pq.read_schema(tmp_path / e / "BTC-USD" / "2026-06-23.parquet") for e in ("binance", "kraken")]
    for schema in schemas:
        for column in eod_archive.DECIMAL_COLUMNS:
            assert schema.field(column).type == pa.decimal128(28, 8)


async def test_export_parquet_leaves_no_temporary_file_behind(tmp_path):
    rows = [MagicMock(exchange="binance", ticker="BTC/USD", interval="1m",
                      timestamp=datetime(2026, 6, 23, 12), open_price=Decimal("1.00000000"),
                      high_price=Decimal("1.00000000"), low_price=Decimal("1.00000000"),
                      close_price=Decimal("1.00000000"), volume=Decimal("1.00000000"),
                      source_ticker=None, quote_currency="USD", fx_rate=None)]
    db = AsyncMock()
    db.execute.return_value = query_result(rows)

    with patch.object(eod_archive, "PARQUET_BASE_DIR", tmp_path):
        await eod_archive._export_parquet(db, TARGET_DATE)

    assert list(tmp_path.rglob("*.tmp")) == []


# ── Orchestration ────────────────────────────────────────────────────────────

def _session_context(session):
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


async def test_run_eod_job_archives_exports_and_cleans_up():
    session = AsyncMock()
    session.bind = None                      # no advisory lock on a non-PostgreSQL bind

    with (
        patch.object(eod_archive, "AsyncSessionLocal", return_value=_session_context(session)),
        patch.object(eod_archive, "_start_run", new_callable=AsyncMock),
        patch.object(eod_archive, "_finish_run", new_callable=AsyncMock) as finish,
        patch.object(eod_archive, "_archive_date", new_callable=AsyncMock, return_value=(2, 1)) as archive,
        patch.object(eod_archive, "_export_parquet", new_callable=AsyncMock, return_value=3) as export,
        patch.object(eod_archive, "_cleanup_old_candles", new_callable=AsyncMock, return_value=4) as cleanup,
    ):
        result = await eod_archive.run_eod_job(TARGET_DATE)

    archive.assert_awaited_once_with(session, TARGET_DATE)
    export.assert_awaited_once_with(session, TARGET_DATE)
    cleanup.assert_awaited_once_with(session)

    assert (result.inserted, result.skipped_duplicate) == (2, 1)
    assert (result.files_written, result.deleted) == (3, 4)
    assert finish.await_args.args[2] == "success"


async def test_run_eod_job_exports_parquet_even_when_nothing_new_was_archived():
    """
    Export used to be gated on `archived > 0`, so re-archiving a day whose hot
    candles had already been cleaned up produced no file at all.
    """
    session = AsyncMock()
    session.bind = None

    with (
        patch.object(eod_archive, "AsyncSessionLocal", return_value=_session_context(session)),
        patch.object(eod_archive, "_start_run", new_callable=AsyncMock),
        patch.object(eod_archive, "_finish_run", new_callable=AsyncMock),
        patch.object(eod_archive, "_archive_date", new_callable=AsyncMock, return_value=(0, 0)),
        patch.object(eod_archive, "_export_parquet", new_callable=AsyncMock, return_value=1) as export,
        patch.object(eod_archive, "_cleanup_old_candles", new_callable=AsyncMock, return_value=0),
    ):
        await eod_archive.run_eod_job(TARGET_DATE)

    export.assert_awaited_once_with(session, TARGET_DATE)


async def test_run_eod_job_replace_clears_the_day_first():
    session = AsyncMock()
    session.bind = None

    with (
        patch.object(eod_archive, "AsyncSessionLocal", return_value=_session_context(session)),
        patch.object(eod_archive, "_start_run", new_callable=AsyncMock),
        patch.object(eod_archive, "_finish_run", new_callable=AsyncMock),
        patch.object(eod_archive, "_delete_history_for", new_callable=AsyncMock) as drop,
        patch.object(eod_archive, "_archive_date", new_callable=AsyncMock, return_value=(2, 0)),
        patch.object(eod_archive, "_export_parquet", new_callable=AsyncMock, return_value=1),
        patch.object(eod_archive, "_cleanup_old_candles", new_callable=AsyncMock, return_value=0),
    ):
        await eod_archive.run_eod_job(TARGET_DATE, replace=True)

    drop.assert_awaited_once_with(session, TARGET_DATE)


async def test_run_eod_job_dry_run_changes_nothing():
    session = AsyncMock()
    session.bind = None

    with (
        patch.object(eod_archive, "AsyncSessionLocal", return_value=_session_context(session)),
        patch.object(eod_archive, "_describe_pending", new_callable=AsyncMock,
                     return_value=eod_archive.ArchiveResult(TARGET_DATE, inserted=5)),
        patch.object(eod_archive, "_start_run", new_callable=AsyncMock) as start,
        patch.object(eod_archive, "_archive_date", new_callable=AsyncMock) as archive,
        patch.object(eod_archive, "_cleanup_old_candles", new_callable=AsyncMock) as cleanup,
    ):
        result = await eod_archive.run_eod_job(TARGET_DATE, dry_run=True)

    assert result.inserted == 5
    start.assert_not_awaited()
    archive.assert_not_awaited()
    cleanup.assert_not_awaited()


async def test_run_eod_job_records_a_failure_and_reraises():
    session = AsyncMock()
    session.bind = None
    boom = RuntimeError("database went away")

    with (
        patch.object(eod_archive, "AsyncSessionLocal", return_value=_session_context(session)),
        patch.object(eod_archive, "_start_run", new_callable=AsyncMock),
        patch.object(eod_archive, "_finish_run", new_callable=AsyncMock) as finish,
        patch.object(eod_archive, "_archive_date", new_callable=AsyncMock, side_effect=boom),
    ):
        try:
            await eod_archive.run_eod_job(TARGET_DATE)
        except RuntimeError as error:
            assert error is boom
        else:
            raise AssertionError("run_eod_job swallowed the failure")

    assert finish.await_args.args[2] == "failure"
    assert "database went away" in finish.await_args.kwargs["error"]


# ── replace mode ─────────────────────────────────────────────────────────────

async def test_replace_refuses_when_the_source_candles_are_gone(db_session):
    """
    Retention deletes hot candles once they are archived, so by the time anyone
    reaches for --replace the source is usually gone. Deleting the day's
    history then would wipe the archive and re-insert nothing.
    """
    db_session.add(CandleHistory(
        exchange="binance", ticker="BTC/USD", interval="1m",
        trade_date=TARGET_DATE, timestamp=datetime(2026, 6, 23, 12),
        open_price=1, high_price=1, low_price=1, close_price=1, volume=1,
    ))
    await db_session.commit()

    with pytest.raises(eod_archive.NothingToReplaceError):
        await eod_archive._delete_history_for(db_session, TARGET_DATE)

    assert await _history_count(db_session) == 1          # archive untouched


async def test_replace_only_removes_history_the_hot_table_can_rebuild(db_session):
    reproducible = datetime(2026, 6, 23, 12, 0)
    orphaned = datetime(2026, 6, 23, 13, 0)

    db_session.add(make_candle(reproducible))             # source still present
    await db_session.commit()
    db_session.add_all([
        CandleHistory(exchange="binance", ticker="BTC/USD", interval="1m",
                      trade_date=TARGET_DATE, timestamp=reproducible,
                      open_price=1, high_price=1, low_price=1, close_price=1, volume=1),
        CandleHistory(exchange="binance", ticker="BTC/USD", interval="1m",
                      trade_date=TARGET_DATE, timestamp=orphaned,
                      open_price=1, high_price=1, low_price=1, close_price=1, volume=1),
    ])
    await db_session.commit()

    deleted = await eod_archive._delete_history_for(db_session, TARGET_DATE)

    assert deleted == 1
    remaining = (await db_session.execute(select(CandleHistory.timestamp))).scalars().all()
    assert remaining == [orphaned]                        # unreproducible row kept
