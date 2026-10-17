"""Instrument names, the localized market list, and the server-rendered page head."""

import json
import re
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import status
from sqlalchemy import select

from app import seo
from app.models.exchange import Exchange, Symbol
from app.models.instrument import Instrument
from app.models.seeder import seed_instruments
from tests.conftest import TestingSessionLocal

TEMPLATE = """<!doctype html>
<html lang="en" class="dark">
  <head>
    <meta charset="UTF-8" />
    <title data-seo>TradingMaster</title>
    <meta data-seo name="description" content="default" />
    <!--app-head-->
  </head>
  <body><div id="root"></div></body>
</html>"""

BASE = "https://tm.example"


@pytest_asyncio.fixture
async def collected(db_session):
    """BTC (crypto, binance) and PKN.WA (stock, yahoo) markets, with the catalogue seeded."""
    binance = Exchange(name="binance", method="multi")
    yahoo = Exchange(name="yahoo", method="poll", asset_class="stock")
    db_session.add_all([binance, yahoo])
    await db_session.flush()
    db_session.add_all([
        Symbol(exchange_id=binance.id, ticker="BTC/USDT", interval="1m"),
        Symbol(exchange_id=yahoo.id, ticker="PKN.WA/PLN", interval="1m"),
        Symbol(exchange_id=binance.id, ticker="NEWCOIN/USDT", interval="1m"),
    ])
    await db_session.commit()
    await seed_instruments(db_session)


@pytest.fixture
def test_db_for_seo():
    """app.seo and the sitemap route open their own sessions — point them at the test DB."""
    with patch("app.seo.AsyncSessionLocal", TestingSessionLocal), \
         patch("app.main.AsyncSessionLocal", TestingSessionLocal):
        yield


# ── Seeding ──────────────────────────────────────────────────────────────────

async def test_seed_instruments_is_insert_only(db_session):
    first = await seed_instruments(db_session)
    btc = await db_session.get(Instrument, "BTC")
    btc.name = "Bitcoin (renamed by an operator)"
    await db_session.commit()

    second = await seed_instruments(db_session)

    assert first >= 65 and second == 0
    assert (await db_session.get(Instrument, "BTC")).name == "Bitcoin (renamed by an operator)"


# ── Market list ──────────────────────────────────────────────────────────────

async def test_markets_say_what_each_one_is(client, collected):
    data = {m["ticker"]: m for m in (await client.get("/api/v1/market/markets")).json()["data"]}

    btc, orlen = data["BTC/USD"], data["PKN.WA/USD"]
    assert (btc["name"], btc["slug"], btc["category_label"]) == ("Bitcoin", "bitcoin-btc", "Digital currency")
    assert btc["description"] == "Bitcoin (BTC) is a cryptocurrency. Category: Digital currency."
    assert (orlen["name"], orlen["venue"], orlen["ticker_symbol"]) == ("ORLEN S.A.", "GPW", "WSE:PKN")
    # A market nobody has named yet still has a name and a page.
    assert (data["NEWCOIN/USD"]["name"], data["NEWCOIN/USD"]["slug"]) == ("NEWCOIN", "newcoin")


async def test_markets_in_polish(client, collected):
    data = {m["ticker"]: m for m in (await client.get("/api/v1/market/markets?lang=pl")).json()["data"]}

    assert data["BTC/USD"]["name"] == "Bitcoin"                        # proper nouns stay as they are
    assert data["BTC/USD"]["asset_class_label"] == "Kryptowaluta"
    assert data["PKN.WA/USD"]["category_label"] == "Energetyka"


async def test_unsupported_language_is_a_422(client, collected):
    response = await client.get("/api/v1/market/markets?lang=xx")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


# ── /instruments ─────────────────────────────────────────────────────────────

async def test_instrument_by_slug(client, collected):
    response = await client.get("/api/v1/instruments/orlen-pkn-wa?lang=de")

    assert response.status_code == status.HTTP_200_OK
    market = response.json()["data"]
    assert market["ticker"] == "PKN.WA/USD"
    assert market["exchanges"] == ["yahoo"]
    assert market["category_label"] == "Energie"


async def test_unknown_slug_is_a_404(client, collected):
    assert (await client.get("/api/v1/instruments/nothing-here")).status_code == status.HTTP_404_NOT_FOUND


async def test_instrument_directory_lists_the_catalogue(client, collected):
    data = (await client.get("/api/v1/instruments?lang=fr")).json()["data"]

    apple = next(i for i in data if i["symbol"] == "AAPL")
    assert apple["name"] == "Apple Inc."
    assert apple["category_label"] == "Technologies de l'information"


async def test_naming_a_new_market(client, collected):
    response = await client.put(
        "/api/v1/instruments/NEWCOIN",
        json={"name": "New Coin Network", "short_name": "New Coin", "category": "defi"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["data"]["slug"] == "new-coin-newcoin"
    markets = {m["ticker"]: m for m in (await client.get("/api/v1/market/markets")).json()["data"]}
    assert markets["NEWCOIN/USD"]["name"] == "New Coin Network"


@pytest.mark.parametrize("body", [
    {"name": "X", "category": "not_a_category"},
    {"name": "X", "asset_class": "stock", "category": "currency"},     # a crypto category on a stock
    {"name": "X", "venue": "LSE"},
    {"name": ""},
])
async def test_naming_rejects_unknown_codes(client, collected, body):
    response = await client.put("/api/v1/instruments/NEWCOIN", json=body)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_naming_rejects_a_slug_another_instrument_uses(client, collected):
    # "A B" + C and "A" + B.C both slugify to "a-b-c".
    first = await client.put("/api/v1/instruments/C", json={"name": "A B"})
    clash = await client.put("/api/v1/instruments/B.C", json={"name": "A"})

    assert first.json()["data"]["slug"] == "a-b-c"
    assert clash.status_code == status.HTTP_409_CONFLICT


async def test_naming_requires_sign_in(anonymous_client, collected):
    response = await anonymous_client.put("/api/v1/instruments/NEWCOIN", json={"name": "X"})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ── Server-rendered head ─────────────────────────────────────────────────────

def _head(document: str) -> str:
    return document.split("</head>")[0]


async def test_market_page_head_in_polish(collected, test_db_for_seo):
    page = await seo.resolve_page("pl", "markets/bitcoin-btc", BASE)
    document = seo.render(TEMPLATE, page, BASE)
    head = _head(document)

    assert page.status == 200
    assert '<html lang="pl" class="dark">' in document
    assert "<title data-seo>Bitcoin (BTC) – kurs dzisiaj, wykres na żywo | TradingMaster</title>" in head
    assert 'content="default"' not in head and head.count("<title") == 1     # template defaults replaced
    assert f'<link data-seo rel="canonical" href="{BASE}/pl/markets/bitcoin-btc">' in head
    hreflangs = re.findall(r'hreflang="([^"]+)" href="([^"]+)"', head)
    assert dict(hreflangs) == {
        "en": f"{BASE}/markets/bitcoin-btc", "pl": f"{BASE}/pl/markets/bitcoin-btc",
        "de": f"{BASE}/de/markets/bitcoin-btc", "fr": f"{BASE}/fr/markets/bitcoin-btc",
        "no": f"{BASE}/no/markets/bitcoin-btc", "it": f"{BASE}/it/markets/bitcoin-btc",
        "es": f"{BASE}/es/markets/bitcoin-btc", "x-default": f"{BASE}/markets/bitcoin-btc",
    }
    assert 'property="og:locale" content="pl_PL"' in head
    assert "noindex" not in head


async def test_stock_page_json_ld_names_the_listed_company(collected, test_db_for_seo):
    page = await seo.resolve_page("en", "markets/orlen-pkn-wa", BASE)
    head = _head(seo.render(TEMPLATE, page, BASE))

    block = re.search(r'<script data-seo type="application/ld\+json">(.*?)</script>', head).group(1)
    graph = json.loads(block)["@graph"]
    assert graph[0]["about"] == {"@type": "Corporation", "name": "ORLEN S.A.", "tickerSymbol": "WSE:PKN"}
    assert [item["name"] for item in graph[1]["itemListElement"]] == ["Home", "Markets", "ORLEN S.A."]
    assert "share price" in page.title


async def test_unknown_market_is_a_404_with_noindex(collected, test_db_for_seo):
    page = await seo.resolve_page("en", "markets/does-not-exist", BASE)
    head = _head(seo.render(TEMPLATE, page, BASE))

    assert page.status == 404
    assert 'name="robots" content="noindex, nofollow"' in head
    assert 'rel="canonical"' not in head


@pytest.mark.parametrize("path, status_code, noindex", [
    ("", 200, False), ("markets", 200, False), ("history", 200, False),
    ("login", 200, True), ("profile", 200, True), ("system", 200, True),
    ("nope", 404, True), ("markets/a/b", 404, True),
])
async def test_static_pages(path, status_code, noindex):
    page = await seo.resolve_page("de", path, BASE)

    assert (page.status, page.noindex) == (status_code, noindex)


def test_values_are_escaped_in_the_head():
    page = seo.Page(200, "en", "markets/x", 'Evil "</title><script>alert(1)</script>',
                    'A & "B"', json_ld=[{"name": "</script><script>alert(1)</script>"}])
    head = _head(seo.render(TEMPLATE, page, BASE))

    assert "<script>alert(1)" not in head
    assert "&lt;/title&gt;" in head and "&quot;B&quot;" in head
    assert "\\u003c/script>" in head


@pytest.mark.parametrize("full_path, expected", [
    ("", ("en", "")), ("pl", ("pl", "")), ("pl/markets/x", ("pl", "markets/x")),
    ("markets/x", ("en", "markets/x")), ("en/markets/x", (None, "markets/x")), ("xx/markets", ("en", "xx/markets")),
])
def test_split_language(full_path, expected):
    assert seo.split_language(full_path) == expected


def test_localized_path():
    assert seo.localized_path("en", "") == "/"
    assert seo.localized_path("pl", "") == "/pl"
    assert seo.localized_path("no", "markets/dnb-ol") == "/no/markets/dnb-ol"


# ── robots.txt / sitemap.xml ─────────────────────────────────────────────────

async def test_robots_txt_points_at_the_sitemap(anonymous_client, monkeypatch):
    monkeypatch.setattr(seo, "SITE_URL", BASE)

    body = (await anonymous_client.get("/robots.txt")).text

    assert "Disallow: /api/" in body
    assert f"Sitemap: {BASE}/sitemap.xml" in body


async def test_sitemap_lists_every_market_in_every_language(anonymous_client, collected, test_db_for_seo, monkeypatch):
    monkeypatch.setattr(seo, "SITE_URL", BASE)

    response = await anonymous_client.get("/sitemap.xml")

    assert response.headers["content-type"].startswith("application/xml")
    locs = re.findall(r"<loc>([^<]+)</loc>", response.text)
    assert f"{BASE}/pl/markets/orlen-pkn-wa" in locs
    assert f"{BASE}/markets/bitcoin-btc" in locs
    assert len(locs) == (3 + 3) * 7            # home, markets, history + 3 markets, × 7 languages
    assert response.text.count('hreflang="x-default"') == len(locs)
