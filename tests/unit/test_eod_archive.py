from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.jobs import eod_archive
from app.models.candle import Candle


def make_candle(timestamp=datetime(2026, 6, 23, 12, 0)):
    return Candle(
        exchange="binance", ticker="BTC/USD", interval="1m",
        timestamp=timestamp, open_price=Decimal("10.12345678"), high_price=12,
        low_price=9, close_price=Decimal("11.00000001"), volume=5,
        source_ticker="BTC/USDT", quote_currency="USD", fx_rate=Decimal("0.99980000"),
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
    assert row.ticker == "BTC/USD"
    assert row.trade_date == date(2026, 6, 23)
    assert row.close_price == Decimal("11.00000001")
    assert row.source_ticker == "BTC/USDT"
    assert row.quote_currency == "USD"
    assert row.fx_rate == Decimal("0.99980000")
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
        await eod_archive._export_parquet(db, date(2026, 6, 23))

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
        await eod_archive._export_parquet(db, date(2026, 6, 23))

    schemas = [pq.read_schema(tmp_path / e / "BTC-USD" / "2026-06-23.parquet") for e in ("binance", "kraken")]
    for schema in schemas:
        for column in eod_archive.DECIMAL_COLUMNS:
            assert schema.field(column).type == pa.decimal128(28, 8)


async def test_cleanup_old_candles_uses_retention_cutoff():
    db = AsyncMock()
    result = MagicMock(rowcount=3)
    db.execute.return_value = result

    deleted = await eod_archive._cleanup_old_candles(db)

    assert deleted == 3
    query = db.execute.call_args.args[0]
    cutoff = query.whereclause.right.value
    expected = eod_archive.utc_now_naive() - timedelta(days=eod_archive.RETENTION_DAYS)
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
