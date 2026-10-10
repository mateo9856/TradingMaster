"""Market-data sources that aren't ccxt exchanges.

Every crypto exchange is a ccxt id, resolved with getattr(ccxtpro, name). Stocks
come from elsewhere — Yahoo Finance, polled — and are registered here by name,
so the API validation, the seeder and the producer agree on what "yahoo" means
without ever passing that name to ccxt.
"""

from app.helpers.intervals import SUPPORTED_INTERVALS

# Collection method of every polled source (app/kafka/yahoo_source.py).
POLL_METHOD = "poll"

# Yahoo's smallest bar is one minute, so the 30s interval can't be offered.
POLL_INTERVALS: tuple[str, ...] = tuple(i for i in SUPPORTED_INTERVALS if i != "30s")

ASSET_CRYPTO = "crypto"
ASSET_STOCK = "stock"

# name → (collection method, asset class)
NON_CCXT_SOURCES: dict[str, dict[str, str]] = {
    "yahoo": {"method": POLL_METHOD, "asset_class": ASSET_STOCK},
}


def is_non_ccxt_source(name: str) -> bool:
    return name in NON_CCXT_SOURCES


def asset_class_for(name: str) -> str:
    return NON_CCXT_SOURCES.get(name, {}).get("asset_class", ASSET_CRYPTO)


def intervals_for_method(method: str) -> tuple[str, ...]:
    """The intervals an exchange collected with `method` can produce."""
    return POLL_INTERVALS if method == POLL_METHOD else SUPPORTED_INTERVALS
