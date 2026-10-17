"""What each market *is* — names and classification for the unified tickers.

A ticker tells an expert what they are looking at; "BTC/USD" and "PKN.WA/USD"
tell everyone else nothing. Every default market has an entry here: its proper
name, a short name for compact places (pickers, URLs), and a classification —
crypto category, or stock sector / listing venue / country.

Only codes live here. Their labels in each UI language, and the descriptions
built from them, are in app/i18n — proper nouns (Bitcoin, ORLEN S.A.) are never
translated, the taxonomy around them is.

The catalogue is seeded into the `instruments` table (app/models/seeder.py),
which is what the API reads, so a market added later through the API can be
named with PUT /api/v1/instruments/{symbol} without a code change.
"""

import re
import unicodedata
from typing import Optional

from app.helpers.sources import ASSET_CRYPTO, ASSET_STOCK

CRYPTO_CATEGORIES: tuple[str, ...] = (
    "currency", "smart_contract_platform", "layer2", "defi", "exchange_token",
    "meme", "ai", "storage", "oracle", "payments", "infrastructure",
)

# GICS-style sectors.
STOCK_SECTORS: tuple[str, ...] = (
    "technology", "communication_services", "consumer_discretionary", "consumer_staples",
    "financials", "energy", "materials", "industrials", "health_care", "utilities", "real_estate",
)

# Listing venue → the prefix schema.org / market-data sites use in a ticker
# symbol ("NASDAQ:AAPL", "WSE:PKN").
VENUES: dict[str, str] = {
    "NASDAQ": "NASDAQ",
    "NYSE": "NYSE",
    "GPW": "WSE",       # Giełda Papierów Wartościowych w Warszawie
    "XETRA": "ETR",
    "OSE": "OSL",       # Oslo Børs
}


def _crypto(name: str, category: str, short_name: Optional[str] = None) -> dict:
    return {"name": name, "short_name": short_name or name, "asset_class": ASSET_CRYPTO,
            "category": category, "venue": None, "country": None}


def _stock(name: str, short_name: str, sector: str, venue: str, country: str) -> dict:
    return {"name": name, "short_name": short_name, "asset_class": ASSET_STOCK,
            "category": sector, "venue": venue, "country": country}


# Keyed by the unified base symbol — the part of "BASE/USD" before the slash.
CATALOG: dict[str, dict] = {
    # ── Crypto ──────────────────────────────────────────────────────────────
    "BTC":    _crypto("Bitcoin", "currency"),
    "ETH":    _crypto("Ethereum", "smart_contract_platform"),
    "BNB":    _crypto("BNB", "exchange_token"),
    "SOL":    _crypto("Solana", "smart_contract_platform"),
    "XRP":    _crypto("XRP", "payments"),
    "ADA":    _crypto("Cardano", "smart_contract_platform"),
    "DOGE":   _crypto("Dogecoin", "meme"),
    "AVAX":   _crypto("Avalanche", "smart_contract_platform"),
    "DOT":    _crypto("Polkadot", "infrastructure"),
    "LINK":   _crypto("Chainlink", "oracle"),
    "LTC":    _crypto("Litecoin", "currency"),
    "TRX":    _crypto("TRON", "smart_contract_platform"),
    "POL":    _crypto("Polygon", "layer2"),
    "SHIB":   _crypto("Shiba Inu", "meme"),
    "UNI":    _crypto("Uniswap", "defi"),
    "ATOM":   _crypto("Cosmos", "infrastructure"),
    "XLM":    _crypto("Stellar", "payments"),
    "BCH":    _crypto("Bitcoin Cash", "currency"),
    "NEAR":   _crypto("NEAR Protocol", "smart_contract_platform", "NEAR"),
    "APT":    _crypto("Aptos", "smart_contract_platform"),
    "SUI":    _crypto("Sui", "smart_contract_platform"),
    "TON":    _crypto("Toncoin", "smart_contract_platform"),
    "PEPE":   _crypto("Pepe", "meme"),
    "ARB":    _crypto("Arbitrum", "layer2"),
    "OP":     _crypto("Optimism", "layer2"),
    "INJ":    _crypto("Injective", "defi"),
    "FIL":    _crypto("Filecoin", "storage"),
    "ICP":    _crypto("Internet Computer", "smart_contract_platform"),
    "HBAR":   _crypto("Hedera", "smart_contract_platform"),
    "VET":    _crypto("VeChain", "smart_contract_platform"),
    "AAVE":   _crypto("Aave", "defi"),
    "RENDER": _crypto("Render", "ai"),
    "ALGO":   _crypto("Algorand", "smart_contract_platform"),
    "ETC":    _crypto("Ethereum Classic", "smart_contract_platform"),
    "SEI":    _crypto("Sei", "smart_contract_platform"),
    "TIA":    _crypto("Celestia", "infrastructure"),
    "FET":    _crypto("Artificial Superintelligence Alliance", "ai", "ASI Alliance"),
    "IMX":    _crypto("Immutable", "layer2"),
    "WIF":    _crypto("dogwifhat", "meme"),
    "STX":    _crypto("Stacks", "layer2"),

    # ── Stocks: United States ───────────────────────────────────────────────
    "AAPL":  _stock("Apple Inc.", "Apple", "technology", "NASDAQ", "US"),
    "MSFT":  _stock("Microsoft Corporation", "Microsoft", "technology", "NASDAQ", "US"),
    "NVDA":  _stock("NVIDIA Corporation", "NVIDIA", "technology", "NASDAQ", "US"),
    "AMZN":  _stock("Amazon.com, Inc.", "Amazon", "consumer_discretionary", "NASDAQ", "US"),
    "GOOGL": _stock("Alphabet Inc. (Class A)", "Alphabet", "communication_services", "NASDAQ", "US"),
    "META":  _stock("Meta Platforms, Inc.", "Meta", "communication_services", "NASDAQ", "US"),
    "TSLA":  _stock("Tesla, Inc.", "Tesla", "consumer_discretionary", "NASDAQ", "US"),
    "JPM":   _stock("JPMorgan Chase & Co.", "JPMorgan Chase", "financials", "NYSE", "US"),
    "V":     _stock("Visa Inc.", "Visa", "financials", "NYSE", "US"),
    "AMD":   _stock("Advanced Micro Devices, Inc.", "AMD", "technology", "NASDAQ", "US"),

    # ── Stocks: Poland (GPW, Warsaw) ────────────────────────────────────────
    "PKN.WA": _stock("ORLEN S.A.", "Orlen", "energy", "GPW", "PL"),
    "PKO.WA": _stock("PKO Bank Polski S.A.", "PKO BP", "financials", "GPW", "PL"),
    "PZU.WA": _stock("Powszechny Zakład Ubezpieczeń S.A.", "PZU", "financials", "GPW", "PL"),
    "PEO.WA": _stock("Bank Polska Kasa Opieki S.A.", "Bank Pekao", "financials", "GPW", "PL"),
    "CDR.WA": _stock("CD PROJEKT S.A.", "CD Projekt", "communication_services", "GPW", "PL"),
    "ALE.WA": _stock("Allegro.eu S.A.", "Allegro", "consumer_discretionary", "GPW", "PL"),
    "LPP.WA": _stock("LPP S.A.", "LPP", "consumer_discretionary", "GPW", "PL"),
    "KGH.WA": _stock("KGHM Polska Miedź S.A.", "KGHM", "materials", "GPW", "PL"),
    "DNP.WA": _stock("Dino Polska S.A.", "Dino Polska", "consumer_staples", "GPW", "PL"),
    "SPL.WA": _stock("Santander Bank Polska S.A.", "Santander Bank Polska", "financials", "GPW", "PL"),

    # ── Stocks: Germany (Xetra) ─────────────────────────────────────────────
    "SAP.DE": _stock("SAP SE", "SAP", "technology", "XETRA", "DE"),
    "SIE.DE": _stock("Siemens AG", "Siemens", "industrials", "XETRA", "DE"),
    "ALV.DE": _stock("Allianz SE", "Allianz", "financials", "XETRA", "DE"),

    # ── Stocks: Norway (Oslo Børs) ──────────────────────────────────────────
    "EQNR.OL": _stock("Equinor ASA", "Equinor", "energy", "OSE", "NO"),
    "DNB.OL":  _stock("DNB Bank ASA", "DNB", "financials", "OSE", "NO"),
}

# Letters NFKD can't strip an accent from.
_TRANSLITERATE = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "ß": "ss", "đ": "d"})
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """ASCII, lower-case, hyphen-separated: "KGHM Polska Miedź" → "kghm-polska-miedz"."""
    ascii_text = unicodedata.normalize("NFKD", text.translate(_TRANSLITERATE))
    ascii_text = ascii_text.encode("ascii", "ignore").decode("ascii").lower()
    return _NON_SLUG.sub("-", ascii_text).strip("-")


def instrument_slug(short_name: str, symbol: str) -> str:
    """
    The URL segment of a market page: name and symbol, "bitcoin-btc",
    "orlen-pkn-wa". The symbol keeps it unique and lets a reader recognise the
    ticker; the name is what people search for. A name that already is the
    symbol isn't repeated ("bnb", not "bnb-bnb"; "pzu-wa", not "pzu-pzu-wa").
    """
    name_part, symbol_part = slugify(short_name), slugify(symbol)
    if not name_part or name_part in (symbol_part, slugify(symbol.split(".")[0])):
        return symbol_part
    return f"{name_part}-{symbol_part}"


def ticker_symbol(symbol: str, venue: Optional[str]) -> Optional[str]:
    """Exchange-qualified ticker for structured data: ("PKN.WA", "GPW") → "WSE:PKN"."""
    if not venue or venue not in VENUES:
        return None
    return f"{VENUES[venue]}:{symbol.split('.')[0]}"


def catalog_rows() -> list[dict]:
    """The catalogue as `instruments` rows."""
    return [
        {"symbol": symbol, "slug": instrument_slug(entry["short_name"], symbol), **entry}
        for symbol, entry in CATALOG.items()
    ]
