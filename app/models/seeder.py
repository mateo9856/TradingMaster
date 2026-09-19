"""
DB Seeder — runs on FastAPI startup.

Inserts the default exchanges and markets (ticker × interval) into the
database if not already present. Safe on every startup: existing rows are
never modified, only missing ones are added — so an existing database picks
up newly added default pairs/intervals on its next start.

Adding a new exchange or symbol:
  1. POST /api/v1/exchanges/{id}/symbols (or /symbols/bulk), or insert a row
  2. The producer picks it up within PRODUCER_CONFIG_REFRESH_SECONDS and the
     Flink job stores it — no restart or code deploy needed.

Every default exchange lists at most one market per coin: the unified feed
publishes one USD ticker per coin and exchange (BTC/USDT and BTC/USD on the
same exchange would both be BTC/USD).
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.helpers.intervals import SUPPORTED_INTERVALS
from app.helpers.markets import unified_ticker
from app.models.exchange import Exchange, Symbol

logger = logging.getLogger(__name__)

# Every default market is collected at every supported interval.
DEFAULT_INTERVALS: tuple[str, ...] = SUPPORTED_INTERVALS

DEFAULT_EXCHANGES = [
    {
        "name":    "binance",
        "method":  "multi",       # watchOHLCVForSymbols (+ trades for 30s)
        "tickers": [
            "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
            "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT",
            "LTC/USDT", "TRX/USDT", "POL/USDT", "SHIB/USDT", "UNI/USDT",
            "ATOM/USDT", "XLM/USDT", "BCH/USDT", "NEAR/USDT", "APT/USDT",
        ],
    },
    {
        "name":    "kraken",
        "method":  "ohlcv",       # watchOHLCV per symbol+interval (+ trades for 30s)
        "tickers": [
            "BTC/USDT", "ETH/USDT",
            "SOL/USD", "XRP/USD", "ADA/USD", "DOGE/USD", "DOT/USD",
            "LINK/USD", "LTC/USD", "AVAX/USD", "ATOM/USD", "XLM/USD",
            "BCH/USD", "UNI/USD", "TRX/USD", "NEAR/USD",
        ],
    },
    {
        "name":    "coinbase",
        "method":  "trades",      # watchTrades → candle aggregation for every interval
        "tickers": [
            "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD",
            "DOGE/USD", "AVAX/USD", "DOT/USD", "LINK/USD", "LTC/USD",
            "BCH/USD", "UNI/USD", "ATOM/USD", "XLM/USD", "SHIB/USD",
        ],
    },
]


def _unified_or_none(ticker: str) -> str | None:
    try:
        return unified_ticker(ticker)
    except ValueError:
        return None


async def seed_exchanges(db: AsyncSession) -> None:
    """
    Inserts default exchanges and symbols into the DB if they don't exist yet.
    Safe to call on every startup — skips rows that already exist, and skips a
    default market whose unified ticker is already fed by another market on
    that exchange (e.g. a user-added SOL/USDT blocks the default SOL/USD).
    """
    for exc_config in DEFAULT_EXCHANGES:
        # Check if exchange already exists
        result = await db.execute(
            select(Exchange).where(Exchange.name == exc_config["name"])
        )
        exchange = result.scalar_one_or_none()

        if not exchange:
            exchange = Exchange(
                name=exc_config["name"],
                method=exc_config["method"],
            )
            db.add(exchange)
            await db.flush()  # get the id without full commit
            logger.info(f"Seeded exchange: {exc_config['name']}")

        # One query per exchange for everything it already has
        result = await db.execute(
            select(Symbol.ticker, Symbol.interval).where(Symbol.exchange_id == exchange.id)
        )
        rows = result.all()
        existing = {(ticker, interval) for ticker, interval in rows}
        unified_in_use = {(_unified_or_none(ticker), interval) for ticker, interval in rows}

        added = 0
        for ticker in exc_config["tickers"]:
            unified = unified_ticker(ticker)
            for interval in DEFAULT_INTERVALS:
                if (ticker, interval) in existing or (unified, interval) in unified_in_use:
                    continue
                db.add(Symbol(exchange_id=exchange.id, ticker=ticker, interval=interval))
                unified_in_use.add((unified, interval))
                added += 1
        if added:
            logger.info(f"  Seeded {added} symbol row(s) for {exc_config['name']}")

    await db.commit()
    logger.info("Exchange/symbol seeding complete")
