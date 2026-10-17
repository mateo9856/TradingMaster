"""
Server-side translations: instrument taxonomy and SEO text.

The UI translates its own text (frontend/src/locales). What the server owns is
what it says *about* instruments — category, sector and exchange labels, the
one-line description built from them — and the page titles/descriptions it
writes into the HTML head for crawlers (app/seo.py). Keeping those here means
the API, the UI and a crawler all see the same words.

Proper nouns (Bitcoin, ORLEN S.A.) are never translated. Descriptions are
templates over the structured fields with labels after a colon ("Category:
Meme coin"), so no language has to inflect a label mid-sentence.

Every locale file must have exactly the keys of en.json (enforced by a test);
a key missing at runtime falls back to English rather than failing.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "pl", "de", "fr", "no", "it", "es")
DEFAULT_LANGUAGE = "en"

# BCP 47 tag for Open Graph's og:locale and similar — language plus its main region.
OG_LOCALES: dict[str, str] = {
    "en": "en_US", "pl": "pl_PL", "de": "de_DE", "fr": "fr_FR", "no": "nb_NO", "it": "it_IT", "es": "es_ES",
}

_LOCALES_DIR = Path(__file__).resolve().parent / "locales"


@lru_cache(maxsize=None)
def catalog(lang: str) -> dict[str, Any]:
    with open(_LOCALES_DIR / f"{lang}.json", encoding="utf-8") as handle:
        return json.load(handle)


def validate_language(lang: Optional[str]) -> str:
    """The language code, `en` when not given, ValueError when unsupported."""
    if lang is None or not lang.strip():
        return DEFAULT_LANGUAGE
    code = lang.strip().lower()
    if code not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language '{lang}' — supported: {', '.join(SUPPORTED_LANGUAGES)}")
    return code


def _lookup(lang: str, key: str) -> Optional[str]:
    node: Any = catalog(lang)
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def t(lang: str, key: str, **params: Any) -> str:
    """Translated text for a dotted key, formatted with `params`. Falls back to English, then to the key."""
    text = _lookup(lang, key) if lang in SUPPORTED_LANGUAGES else None
    if text is None:
        text = _lookup(DEFAULT_LANGUAGE, key)
    if text is None:
        return key
    return text.format(**params) if params else text


def label(lang: str, group: str, code: Optional[str]) -> Optional[str]:
    """A taxonomy label ("category", "sector", "venue", "asset_class"); the raw code if untranslated."""
    if not code:
        return None
    text = t(lang, f"{group}.{code}")
    return code if text == f"{group}.{code}" else text


def category_group(asset_class: str) -> str:
    """Stocks are classified by sector, crypto by category — both stored in `category`."""
    return "sector" if asset_class == "stock" else "category"


def describe(lang: str, *, name: str, symbol: str, asset_class: str,
             category: Optional[str], venue: Optional[str]) -> str:
    """The one-line description of an instrument, e.g. "Bitcoin (BTC) is a cryptocurrency. Category: …"."""
    category_label = label(lang, category_group(asset_class), category)
    venue_label = label(lang, "venue", venue)
    if asset_class == "stock" and category_label:
        key = "description.stock" if venue_label else "description.stock_no_venue"
        return t(lang, key, name=name, symbol=symbol, category=category_label, venue=venue_label)
    if asset_class != "stock" and category_label:
        return t(lang, "description.crypto", name=name, symbol=symbol, category=category_label)
    return t(lang, "description.unclassified", name=name, symbol=symbol)
