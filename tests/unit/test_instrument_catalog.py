import re

import pytest

from app.helpers.instruments import (
    CATALOG,
    CRYPTO_CATEGORIES,
    STOCK_SECTORS,
    VENUES,
    catalog_rows,
    instrument_slug,
    slugify,
    ticker_symbol,
)
from app.helpers.markets import split_symbol
from app.models.seeder import DEFAULT_EXCHANGES


def test_every_default_market_is_named():
    defaults = {split_symbol(t)[0] for e in DEFAULT_EXCHANGES for t in e["tickers"]}
    assert defaults <= set(CATALOG), f"unnamed: {sorted(defaults - set(CATALOG))}"


def test_slugs_are_unique_lowercase_ascii():
    slugs = [row["slug"] for row in catalog_rows()]
    assert len(slugs) == len(set(slugs))
    assert all(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug) for slug in slugs)


def test_classification_uses_known_codes():
    for symbol, entry in CATALOG.items():
        allowed = STOCK_SECTORS if entry["asset_class"] == "stock" else CRYPTO_CATEGORIES
        assert entry["category"] in allowed, symbol
        if entry["asset_class"] == "stock":
            assert entry["venue"] in VENUES and entry["country"], symbol


@pytest.mark.parametrize("short_name, symbol, expected", [
    ("Bitcoin", "BTC", "bitcoin-btc"),
    ("Orlen", "PKN.WA", "orlen-pkn-wa"),
    ("PZU", "PZU.WA", "pzu-wa"),
    ("BNB", "BNB", "bnb"),
    ("KGHM Polska Miedź", "KGH.WA", "kghm-polska-miedz-kgh-wa"),
    ("Łódź Øre", "X", "lodz-ore-x"),
])
def test_instrument_slug(short_name, symbol, expected):
    assert instrument_slug(short_name, symbol) == expected


def test_slugify_strips_everything_but_ascii_words():
    assert slugify("  Amazon.com, Inc. ") == "amazon-com-inc"


def test_ticker_symbol_uses_the_venue_prefix():
    assert ticker_symbol("PKN.WA", "GPW") == "WSE:PKN"
    assert ticker_symbol("AAPL", "NASDAQ") == "NASDAQ:AAPL"
    assert ticker_symbol("BTC", None) is None


def test_key_names():
    assert CATALOG["BTC"]["name"] == "Bitcoin"
    assert CATALOG["AAPL"]["name"] == "Apple Inc."
    assert CATALOG["PKN.WA"]["name"] == "ORLEN S.A."
