from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

from app.jobs import eod_archive
from app.models.candle import Candle


def make_candle(timestamp=datetime(2026, 6, 23, 12, 0)):
    return Candle(
        exchange="binance", ticker="BTC/USDT", interval="1m",
        timestamp=timestamp, open_price=10, high_price=12,
        low_price=9, close_price=11, volume=5,
    )


def query_result(rows):
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


async def test_archive_date_copies_candles_to_history():
    candle = make_candle()
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.execute.return_value = query_result([candle])

    archived = await eod_archive._archive_date(db, date(2026, 6, 23))

    assert archived == 1
    row = db.add_all.call_args.args[0][0]
    assert row.exchange == "binance"
    assert row.trade_date == date(2026, 6, 23)
    assert row.close_price == 11
    db.commit.assert_awaited_once()


async def test_archive_date_skips_commit_when_no_candles():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.execute.return_value = query_result([])

    assert await eod_archive._archive_date(db, date(2026, 6, 23)) == 0
    db.add_all.assert_not_called()
    db.commit.assert_not_awaited()


async def test_export_parquet_groups_by_exchange_and_ticker(tmp_path):
    rows = [
        MagicMock(exchange="binance", ticker="BTC/USDT", interval="1m",
                  timestamp=datetime(2026, 6, 23, 12), open_price=10,
                  high_price=12, low_price=9, close_price=11, volume=5),
        MagicMock(exchange="kraken", ticker="ETH/USD", interval="1m",
                  timestamp=datetime(2026, 6, 23, 12), open_price=20,
                  high_price=22, low_price=19, close_price=21, volume=7),
    ]
    db = AsyncMock()
    db.execute.return_value = query_result(rows)

    with patch.object(eod_archive, "PARQUET_BASE_DIR", tmp_path):
        await eod_archive._export_parquet(db, date(2026, 6, 23))

    exported = tmp_path / "binance" / "BTC-USDT" / "2026-06-23.parquet"
    assert exported.exists()
    frame = pd.read_parquet(exported)
    assert list(frame["close_price"]) == [11]
    assert "exchange" not in frame.columns
    assert "ticker" not in frame.columns


async def test_cleanup_old_candles_uses_retention_cutoff():
    db = AsyncMock()
    result = MagicMock(rowcount=3)
    db.execute.return_value = result

    deleted = await eod_archive._cleanup_old_candles(db)

    assert deleted == 3
    query = db.execute.call_args.args[0]
    cutoff = query.whereclause.right.value
    expected = datetime.now(timezone.utc) - timedelta(days=eod_archive.RETENTION_DAYS)
    assert abs((expected - cutoff).total_seconds()) < 5
    db.commit.assert_awaited_once()


async def test_run_eod_job_archives_exports_and_cleans_up():
    session = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(eod_archive, "AsyncSessionLocal", return_value=context),
        patch.object(eod_archive, "_archive_date", new_callable=AsyncMock, return_value=2) as archive,
        patch.object(eod_archive, "_export_parquet", new_callable=AsyncMock) as export,
        patch.object(eod_archive, "_cleanup_old_candles", new_callable=AsyncMock) as cleanup,
    ):
        await eod_archive.run_eod_job(date(2026, 6, 23))

    archive.assert_awaited_once_with(session, date(2026, 6, 23))
    export.assert_awaited_once_with(session, date(2026, 6, 23))
    cleanup.assert_awaited_once_with(session)
