"""
Full end-to-end verification of the EOD archive job against a real (SQLite)
database session — seeds sample candle rows, runs run_eod_job() unmodified
(none of its internal steps are mocked), and checks every side effect it's
documented to have:
  1. candles for the target date are copied into candles_history
  2. those candles are exported to a Parquet file on disk
  3. candles older than RETENTION_DAYS are deleted from the hot `candles` table
  4. candles within the retention window are left alone

This complements tests/unit/test_eod_archive.py, which unit-tests each step
in isolation with mocked internals — this test exercises the whole pipeline
together, the way app/eod_runner.py actually invokes it.
"""

from datetime import timedelta
from unittest.mock import patch

import pandas as pd
import pytest_asyncio
from sqlalchemy import select

from app.helpers.time import utc_now_naive
from app.jobs import eod_archive
from app.models.candle import Candle as CandleORM
from app.models.candle_history import CandleHistory
from tests.conftest import TestingSessionLocal


@pytest_asyncio.fixture
async def seeded_candles(db_session):
    """
    Seeds two candles around the retention boundary:
      - old_candle:    older than RETENTION_DAYS — archived AND cleaned up
      - recent_candle: within RETENTION_DAYS      — left alone entirely
    """
    now = utc_now_naive()
    old_ts = now - timedelta(days=eod_archive.RETENTION_DAYS + 3)
    recent_ts = now - timedelta(days=1)

    old_candle = CandleORM(
        exchange="binance", ticker="BTC/USDT", interval="1m",
        timestamp=old_ts, open_price=100, high_price=110,
        low_price=95, close_price=105, volume=12.5,
    )
    recent_candle = CandleORM(
        exchange="kraken", ticker="ETH/USDT", interval="1m",
        timestamp=recent_ts, open_price=200, high_price=210,
        low_price=195, close_price=205, volume=8.0,
    )
    db_session.add_all([old_candle, recent_candle])
    await db_session.commit()

    return {"old_date": old_ts.date(), "old_ts": old_ts, "recent_ts": recent_ts}


async def test_run_eod_job_archives_exports_and_cleans_up_against_real_db(
    db_session, seeded_candles, tmp_path
):
    old_date = seeded_candles["old_date"]

    with (
        patch.object(eod_archive, "AsyncSessionLocal", TestingSessionLocal),
        patch.object(eod_archive, "PARQUET_BASE_DIR", tmp_path),
    ):
        await eod_archive.run_eod_job(old_date)

    # 1. Archived into candles_history with the source row's data intact.
    history_result = await db_session.execute(
        select(CandleHistory).where(CandleHistory.trade_date == old_date)
    )
    history_rows = history_result.scalars().all()
    assert len(history_rows) == 1
    assert history_rows[0].exchange == "binance"
    assert history_rows[0].ticker == "BTC/USDT"
    assert history_rows[0].close_price == 105

    # 2. Exported to Parquet.
    parquet_path = tmp_path / "binance" / "BTC-USDT" / f"{old_date}.parquet"
    assert parquet_path.exists()
    frame = pd.read_parquet(parquet_path)
    assert list(frame["close_price"]) == [105]

    # 3. The old (>RETENTION_DAYS) candle was deleted from the hot table...
    hot_result = await db_session.execute(
        select(CandleORM).where(CandleORM.exchange == "binance", CandleORM.ticker == "BTC/USDT")
    )
    assert hot_result.scalars().all() == []

    # 4. ...but the recent candle (within retention) was left alone, both in
    #    the hot table and absent from history (it wasn't the archived date).
    recent_hot = await db_session.execute(
        select(CandleORM).where(CandleORM.exchange == "kraken", CandleORM.ticker == "ETH/USDT")
    )
    assert len(recent_hot.scalars().all()) == 1

    recent_history = await db_session.execute(
        select(CandleHistory).where(CandleHistory.exchange == "kraken")
    )
    assert recent_history.scalars().all() == []


async def test_run_eod_job_is_a_no_op_when_no_candles_for_target_date(db_session, tmp_path):
    """A date with no candles at all should archive nothing and not error."""
    with (
        patch.object(eod_archive, "AsyncSessionLocal", TestingSessionLocal),
        patch.object(eod_archive, "PARQUET_BASE_DIR", tmp_path),
    ):
        await eod_archive.run_eod_job(utc_now_naive().date() - timedelta(days=100))

    assert list(tmp_path.iterdir()) == []
    history_result = await db_session.execute(select(CandleHistory))
    assert history_result.scalars().all() == []
