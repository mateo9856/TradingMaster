from sqlalchemy import select

from app.helpers.intervals import SUPPORTED_INTERVALS
from app.helpers.markets import unified_ticker
from app.helpers.sources import POLL_INTERVALS
from app.models.exchange import Exchange, Symbol
from app.models.seeder import DEFAULT_EXCHANGES, DEFAULT_INTERVALS, seed_exchanges

# Every default market at every interval its exchange produces (no 30s for stocks).
TOTAL_ROWS = sum(len(e["tickers"]) * len(e.get("intervals", DEFAULT_INTERVALS)) for e in DEFAULT_EXCHANGES)
EXCHANGE_NAMES = {"binance", "kraken", "coinbase", "yahoo"}


async def symbol_rows(db):
    result = await db.execute(select(Exchange.name, Symbol.ticker, Symbol.interval).join(Symbol))
    return set(result.all())


async def test_seed_inserts_every_default_ticker_at_every_interval(db_session):
    await seed_exchanges(db_session)

    exchanges = (await db_session.execute(select(Exchange))).scalars().all()
    rows = await symbol_rows(db_session)
    assert {e.name for e in exchanges} == EXCHANGE_NAMES
    assert len(rows) == TOTAL_ROWS
    assert ("binance", "SOL/USDT", "30s") in rows
    assert ("coinbase", "BTC/USD", "1d") in rows


async def test_seed_is_idempotent(db_session):
    await seed_exchanges(db_session)
    first = await symbol_rows(db_session)

    await seed_exchanges(db_session)

    assert await symbol_rows(db_session) == first
    exchanges = (await db_session.execute(select(Exchange))).scalars().all()
    assert len(exchanges) == len(EXCHANGE_NAMES)


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
    assert len(rows) == TOTAL_ROWS
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
    assert {item["name"] for item in DEFAULT_EXCHANGES} == EXCHANGE_NAMES
    assert all(len(item["tickers"]) >= 15 for item in DEFAULT_EXCHANGES)
    assert DEFAULT_INTERVALS == ("30s", "1m", "5m", "1h", "1d")


async def test_seed_adds_stocks_without_30s_and_marks_them_as_stocks(db_session):
    await seed_exchanges(db_session)

    yahoo = (await db_session.execute(select(Exchange).where(Exchange.name == "yahoo"))).scalar_one()
    rows = await symbol_rows(db_session)
    assert yahoo.method == "poll"
    assert yahoo.asset_class == "stock"
    assert ("yahoo", "PKN.WA/PLN", "1m") in rows
    assert ("yahoo", "AAPL/USD", "1d") in rows
    assert {i for (e, _, i) in rows if e == "yahoo"} == set(POLL_INTERVALS)
    binance = (await db_session.execute(select(Exchange).where(Exchange.name == "binance"))).scalar_one()
    assert binance.asset_class == "crypto"


def test_default_stocks_cover_poland_and_the_us():
    yahoo = next(item for item in DEFAULT_EXCHANGES if item["name"] == "yahoo")
    quotes = {t.split("/")[1] for t in yahoo["tickers"]}
    assert {"USD", "PLN", "EUR", "NOK"} <= quotes
    assert sum(t.endswith(".WA/PLN") for t in yahoo["tickers"]) >= 10


def test_default_tickers_are_valid_and_unique_per_unified_ticker():
    for item in DEFAULT_EXCHANGES:
        unified = [unified_ticker(t) for t in item["tickers"]]
        assert len(unified) == len(set(unified)), f"{item['name']} lists one coin twice"
