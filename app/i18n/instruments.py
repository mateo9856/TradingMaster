"""
An instrument as a reader in a given language sees it — shared by the API
(market list, instrument endpoints) and the server-rendered page head.

A market with no `instruments` row still gets a usable entry: its symbol as
the name and a slug from the symbol, so a market added through the API has a
page from the start and can be named later (PUT /api/v1/instruments/{symbol}).
"""

from typing import Optional

from app.helpers.instruments import instrument_slug, slugify, ticker_symbol
from app.helpers.sources import ASSET_CRYPTO
from app.i18n import category_group, describe, label, t
from app.models.instrument import Instrument


def fallback_slug(symbol: str) -> str:
    return slugify(symbol)


def localize(symbol: str, lang: str, instrument: Optional[Instrument], asset_class: Optional[str] = None) -> dict:
    """Name, slug, classification, labels and description of `symbol` in `lang`."""
    if instrument is None:
        asset = asset_class or ASSET_CRYPTO
        name = short_name = symbol
        slug = fallback_slug(symbol)
        category = venue = country = None
    else:
        asset = instrument.asset_class
        name, short_name, slug = instrument.name, instrument.short_name, instrument.slug
        category, venue, country = instrument.category, instrument.venue, instrument.country

    description = describe(lang, name=name, symbol=symbol, asset_class=asset, category=category, venue=venue)
    variant = "stock" if asset == "stock" else "crypto"
    params = {"name": name, "symbol": symbol, "description": description}
    return {
        "symbol": symbol,
        "name": name,
        "short_name": short_name,
        "slug": slug,
        "asset_class": asset,
        "asset_class_label": label(lang, "asset_class", asset),
        "category": category,
        "category_label": label(lang, category_group(asset), category),
        "venue": venue,
        "venue_label": label(lang, "venue", venue),
        "country": country,
        "ticker_symbol": ticker_symbol(symbol, venue),
        "description": description,
        # The market page's <title> and meta description — the server writes the
        # same text into the HTML head (app/seo.py), the UI uses these.
        "page_title": t(lang, f"seo.market_title_{variant}", **params),
        "page_description": t(lang, f"seo.market_description_{variant}", **params),
    }


__all__ = ["fallback_slug", "instrument_slug", "localize"]
