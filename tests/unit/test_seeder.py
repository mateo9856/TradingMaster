from sqlalchemy import select

from app.helpers.intervals import SUPPORTED_INTERVALS
from app.helpers.markets import unified_ticker
from app.models.exchange import Exchange, Symbol
from app.models.seeder import DEFAULT_EXCHANGES, DEFAULT_INTERVALS, seed_exchanges

TOTAL_TICKERS = sum(len(e["tickers"]) for e in DEFAULT_EXCHANGES)


async def symbol_rows(db):
    result = await db.execute(select(Exchange.name, Symbol.ticker, Symbol.interval).join(Symbol))
    return set(result.all())


async def test_seed_inserts_every_default_ticker_at_every_interval(db_session):
    await seed_exchanges(db_session)

    exchanges = (await db_session.execute(select(Exchange))).scalars().all()
    rows = await symbol_rows(db_session)
    assert {e.name for e in exchanges} == {"binance", "kraken", "coinbase"}
    assert len(rows) == TOTAL_TICKERS * len(DEFAULT_INTERVALS)
    assert ("binance", "SOL/USDT", "30s") in rows
    assert ("coinbase", "BTC/USD", "1d") in rows


async def test_seed_is_idempotent(db_session):
    await seed_exchanges(db_session)
    first = await symbol_rows(db_session)

    await seed_exchanges(db_session)

    assert await symbol_rows(db_session) == first
    exchanges = (await db_session.execute(select(Exchange))).scalars().all()
    assert len(exchanges) == 3


async def test_seed_upgrades_an_existing_1m_only_database(db_session):
    # A database seeded by the previous version: 1m only, a handful of pairs,
    # one of them disabled by an operator.
    binance = Exchange(name="binance", method="multi")
    db_session.add(binance)
    await db_session.flush()
    db_session.add_all([
        Symbol(exchange_id=binance.id, ticker="BTC/USDT", interval="1m"),
        Symbol(exchange_id=binance.id, ticker="ETH/USDT", interval="1m", enabled=False),
    ])
    await db_session.commit()

    await seed_exchanges(db_session)

    rows = await symbol_rows(db_session)
    assert {i for (e, t, i) in rows if (e, t) == ("binance", "BTC/USDT")} == set(SUPPORTED_INTERVALS)
    assert len(rows) == TOTAL_TICKERS * len(DEFAULT_INTERVALS)
    # Existing rows are never modified
    eth = (await db_session.execute(
        select(Symbol).where(
            Symbol.exchange_id == binance.id, Symbol.ticker == "ETH/USDT", Symbol.interval == "1m",
        )
    )).scalar_one()
    assert eth.enabled is False


async def test_seed_skips_default_market_clashing_with_user_market(db_session):
    # A user already feeds SOL/USD on kraken from SOL/USDT — the default SOL/USD must not clash.
    kraken = Exchange(name="kraken", method="ohlcv")
    db_session.add(kraken)
    await db_session.flush()
    db_session.add(Symbol(exchange_id=kraken.id, ticker="SOL/USDT", interval="1m"))
    await db_session.commit()

    await seed_exchanges(db_session)

    rows = await symbol_rows(db_session)
    assert ("kraken", "SOL/USD", "1m") not in rows
    assert ("kraken", "SOL/USD", "5m") in rows


async def test_seed_survives_legacy_rows_with_unsupported_quote(db_session):
    binance = Exchange(name="binance", method="multi")
    db_session.add(binance)
    await db_session.flush()
    db_session.add(Symbol(exchange_id=binance.id, ticker="ETH/BTC", interval="1m"))
    await db_session.commit()

    await seed_exchanges(db_session)

    assert ("binance", "ETH/BTC", "1m") in await symbol_rows(db_session)


def test_default_configuration_covers_many_pairs_and_all_intervals():
    assert {item["name"] for item in DEFAULT_EXCHANGES} == {"binance", "kraken", "coinbase"}
    assert all(len(item["tickers"]) >= 15 for item in DEFAULT_EXCHANGES)
    assert DEFAULT_INTERVALS == ("30s", "1m", "5m", "1h", "1d")


def test_default_tickers_are_valid_and_unique_per_unified_ticker():
    for item in DEFAULT_EXCHANGES:
        unified = [unified_ticker(t) for t in item["tickers"]]
        assert len(unified) == len(set(unified)), f"{item['name']} lists one coin twice"
