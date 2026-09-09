"""
DB Seeder — runs on FastAPI startup.

Inserts default exchange and symbol config into the database if not already
present. This replaces the hardcoded EXCHANGE_CONFIG dict in producer.py.

Adding a new exchange or symbol:
  1. Add a row to the exchanges / symbols table in pgAdmin or via psql
  2. Restart the producer — it reads config from DB on startup
  No code deploy needed.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.exchange import Exchange, Symbol

logger = logging.getLogger(__name__)

# Default config — matches the old hardcoded EXCHANGE_CONFIG in producer.py
DEFAULT_EXCHANGES = [
    {
        "name":    "binance",
        "method":  "multi",       # watchOHLCVForSymbols
        "symbols": [
            {"ticker": "BTC/USDT", "interval": "1m"},
            {"ticker": "ETH/USDT", "interval": "1m"},
            {"ticker": "BNB/USDT", "interval": "1m"},
        ],
    },
    {
        "name":    "kraken",
        "method":  "ohlcv",       # watchOHLCV per symbol
        "symbols": [
            {"ticker": "BTC/USDT", "interval": "1m"},
            {"ticker": "ETH/USDT", "interval": "1m"},
        ],
    },
    {
        "name":    "coinbase",
        "method":  "trades",      # watchTrades → manual candle aggregation
        "symbols": [
            {"ticker": "BTC/USD", "interval": "1m"},
            {"ticker": "ETH/USD", "interval": "1m"},
        ],
    },
]


async def seed_exchanges(db: AsyncSession) -> None:
    """
    Inserts default exchanges and symbols into the DB if they don't exist yet.
    Safe to call on every startup — skips rows that already exist.
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

        # Seed symbols for this exchange
        for sym_config in exc_config["symbols"]:
            result = await db.execute(
                select(Symbol).where(
                    Symbol.exchange_id == exchange.id,
                    Symbol.ticker == sym_config["ticker"],
                    Symbol.interval == sym_config["interval"],
                )
            )
            existing = result.scalar_one_or_none()

            if not existing:
                db.add(Symbol(
                    exchange_id=exchange.id,
                    ticker=sym_config["ticker"],
                    interval=sym_config["interval"],
                ))
                logger.info(f"  Seeded symbol: {sym_config['ticker']} {sym_config['interval']}")

    await db.commit()
    logger.info("Exchange/symbol seeding complete")