from unittest.mock import AsyncMock, MagicMock

from app.models.seeder import DEFAULT_EXCHANGES, seed_exchanges


def result_with(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


async def test_seed_exchanges_inserts_default_exchanges_and_symbols():
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.execute.return_value = result_with(None)

    await seed_exchanges(db)

    assert db.add.call_count == 10
    assert db.flush.await_count == 3
    db.commit.assert_awaited_once()


async def test_seed_exchanges_is_safe_when_rows_already_exist():
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    existing = MagicMock(id=1)
    db.execute.return_value = result_with(existing)

    await seed_exchanges(db)

    assert db.add.call_count == 0
    assert db.flush.await_count == 0
    db.commit.assert_awaited_once()


def test_default_exchange_configuration_is_complete():
    assert {item["name"] for item in DEFAULT_EXCHANGES} == {"binance", "kraken", "coinbase"}
    assert all(item["symbols"] for item in DEFAULT_EXCHANGES)
