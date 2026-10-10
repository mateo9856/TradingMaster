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

A default pair an exchange turns out not to list costs nothing: the producer
logs it and skips it (`_available_symbols`), so the lists below err on the side
of breadth.

Stocks come from Yahoo Finance ("yahoo", polled — see app/kafka/yahoo_source.py)
under their Yahoo symbols, quoted in the currency they trade in: PKN.WA/PLN is
PKN Orlen on the Warsaw exchange, converted to USD with the ECB rate on the way
in and shown back in PLN to a Polish reader. London listings are left out on
purpose: Yahoo quotes them in pence (GBp), not pounds.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.helpers.intervals import SUPPORTED_INTERVALS
from app.helpers.markets import unified_ticker
from app.helpers.sources import ASSET_CRYPTO, ASSET_STOCK, POLL_INTERVALS, POLL_METHOD
from app.models.exchange import Exchange, Symbol

logger = logging.getLogger(__name__)

# Every default market is collected at every interval its exchange can produce.
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
            "SUI/USDT", "TON/USDT", "PEPE/USDT", "ARB/USDT", "OP/USDT",
            "INJ/USDT", "FIL/USDT", "ICP/USDT", "HBAR/USDT", "VET/USDT",
            "AAVE/USDT", "RENDER/USDT", "ALGO/USDT", "ETC/USDT", "SEI/USDT",
            "TIA/USDT", "FET/USDT", "IMX/USDT", "WIF/USDT", "STX/USDT",
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
            "SUI/USD", "PEPE/USD", "ARB/USD", "OP/USD", "INJ/USD",
            "FIL/USD", "ICP/USD", "AAVE/USD", "RENDER/USD", "ALGO/USD",
            "ETC/USD", "TIA/USD", "FET/USD", "SEI/USD", "HBAR/USD",
        ],
    },
    {
        "name":    "coinbase",
        "method":  "trades",      # watchTrades → candle aggregation for every interval
        "tickers": [
            "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD",
            "DOGE/USD", "AVAX/USD", "DOT/USD", "LINK/USD", "LTC/USD",
            "BCH/USD", "UNI/USD", "ATOM/USD", "XLM/USD", "SHIB/USD",
            "SUI/USD", "PEPE/USD", "ARB/USD", "OP/USD", "INJ/USD",
            "FIL/USD", "ICP/USD", "HBAR/USD", "AAVE/USD", "RENDER/USD",
            "ALGO/USD", "ETC/USD", "APT/USD", "NEAR/USD", "FET/USD",
        ],
    },
    {
        "name":        "yahoo",
        "method":      POLL_METHOD,   # Yahoo Finance bars, polled (≈15 min delayed)
        "asset_class": ASSET_STOCK,
        "intervals":   POLL_INTERVALS,
        "tickers": [
            # United States (NASDAQ / NYSE)
            "AAPL/USD", "MSFT/USD", "NVDA/USD", "AMZN/USD", "GOOGL/USD",
            "META/USD", "TSLA/USD", "JPM/USD", "V/USD", "AMD/USD",
            # Poland (GPW, Warsaw)
            "PKN.WA/PLN", "PKO.WA/PLN", "PZU.WA/PLN", "PEO.WA/PLN", "CDR.WA/PLN",
            "ALE.WA/PLN", "LPP.WA/PLN", "KGH.WA/PLN", "DNP.WA/PLN", "SPL.WA/PLN",
            # Germany (Xetra)
            "SAP.DE/EUR", "SIE.DE/EUR", "ALV.DE/EUR",
            # Norway (Oslo Børs)
            "EQNR.OL/NOK", "DNB.OL/NOK",
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
                asset_class=exc_config.get("asset_class", ASSET_CRYPTO),
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
            for interval in exc_config.get("intervals", DEFAULT_INTERVALS):
                if (ticker, interval) in existing or (unified, interval) in unified_in_use:
                    continue
                db.add(Symbol(exchange_id=exchange.id, ticker=ticker, interval=interval))
                unified_in_use.add((unified, interval))
                added += 1
        if added:
            logger.info(f"  Seeded {added} symbol row(s) for {exc_config['name']}")

    await db.commit()
    logger.info("Exchange/symbol seeding complete")
