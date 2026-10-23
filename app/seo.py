"""
Search-engine and link-preview metadata, written into the HTML the server sends.

The UI is a single-page app: without this, every URL would answer with the
same generic index.html, so a crawler that doesn't run JavaScript — and every
link preview (Slack, Facebook, LinkedIn) — would see one title for the whole
site. Here, the page for /pl/markets/bitcoin-btc arrives with its own
language, title, description, canonical URL, hreflang alternates, Open Graph
tags and schema.org JSON-LD. The client takes these over once it boots
(frontend/src/lib/seo-tags.ts removes the `data-seo` tags and React renders its
own).

URL scheme: English is unprefixed (/markets/bitcoin-btc), every other language
has a path prefix (/pl/markets/bitcoin-btc). /en/… redirects to the unprefixed
URL so each page has exactly one English address. Nothing is redirected by
Accept-Language: crawlers send none, and Google advises against it. Picking a
language from the visitor's location happens in the browser instead.

Unknown pages and markets answer 404 with `noindex` — a 200 "not found" page
(a soft 404) would get indexed.
"""

import html
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import Request

from app.config import SITE_URL
from app.i18n import DEFAULT_LANGUAGE, OG_LOCALES, SUPPORTED_LANGUAGES, t
from app.models.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

SITE_NAME = "TradingMaster"
HEAD_PLACEHOLDER = "<!--app-head-->"

# Client-side routes (frontend/src/App.tsx) → the SEO text key for them.
STATIC_PAGES: dict[str, str] = {
    "": "home",
    "markets": "markets",
    "history": "history",
    "system": "system",
    "login": "login",
    "profile": "profile",
    "trades": "trades",
}
# Real pages, but nothing a search result should lead to.
NOINDEX_PAGES = {"system", "login", "profile", "trades"}
# Listed in the sitemap, besides one page per market.
SITEMAP_PAGES = ("", "markets", "history")

_SEO_TAG = re.compile(r"\s*<(title|meta|link|script)\b[^>]*\bdata-seo\b[^>]*>(?:.*?</\1>)?", re.S)
_HTML_LANG = re.compile(r'<html\b([^>]*?)\blang="[^"]*"')


@dataclass
class Page:
    """What to put in the head of one response."""
    status: int
    lang: str
    path: str                                   # without the language prefix, no leading slash
    title: str
    description: str
    noindex: bool = False
    json_ld: list[dict] = field(default_factory=list)


# ── URLs ─────────────────────────────────────────────────────────────────────

def site_url(request: Request) -> str:
    """Absolute origin for canonical/sitemap links. SITE_URL in production; the request's own origin otherwise."""
    return (SITE_URL or str(request.base_url)).rstrip("/")


def localized_path(lang: str, path: str) -> str:
    """("pl", "markets/bitcoin-btc") → "/pl/markets/bitcoin-btc"; English has no prefix."""
    path = path.strip("/")
    prefix = "" if lang == DEFAULT_LANGUAGE else f"/{lang}"
    return f"{prefix}/{path}" if path else (prefix or "/")


def split_language(full_path: str) -> tuple[Optional[str], str]:
    """
    "pl/markets/x" → ("pl", "markets/x"); "markets/x" → ("en", "markets/x").
    The language is None for an explicit "en/" prefix, which the caller redirects.
    """
    path = full_path.strip("/")
    first, _, rest = path.partition("/")
    if first == DEFAULT_LANGUAGE:
        return None, rest
    if first in SUPPORTED_LANGUAGES:
        return first, rest
    return DEFAULT_LANGUAGE, path


# ── Page resolution ──────────────────────────────────────────────────────────

def _not_found(lang: str, path: str) -> Page:
    return Page(404, lang, path, t(lang, "seo.not_found_title"), t(lang, "seo.not_found_description"), noindex=True)


async def resolve_page(lang: str, path: str, base: str) -> Page:
    """Title, description, status and structured data for one client route."""
    if path in STATIC_PAGES:
        key = STATIC_PAGES[path]
        description_key = f"seo.{key}_description"
        description = t(lang, description_key)
        page = Page(
            200, lang, path, t(lang, f"seo.{key}_title"),
            "" if description == description_key else description,
            noindex=key in NOINDEX_PAGES,
        )
        if key == "home":
            page.json_ld.append({
                "@context": "https://schema.org", "@type": "WebSite",
                "name": SITE_NAME, "url": base + localized_path(lang, ""), "inLanguage": lang,
            })
        return page

    first, _, slug = path.partition("/")
    if first != "markets" or not slug or "/" in slug:
        return _not_found(lang, path)

    market = await _find_market(slug, lang)
    if market is None:
        return _not_found(lang, path)

    title, description = market.page_title, market.page_description
    url = base + localized_path(lang, path)

    about: dict = {"@type": "Thing", "name": market.name, "alternateName": market.symbol}
    if market.asset_class == "stock":
        about = {"@type": "Corporation", "name": market.name}
        if market.ticker_symbol:
            about["tickerSymbol"] = market.ticker_symbol
    page = Page(200, lang, path, title, description)
    page.json_ld.append({
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebPage", "name": title, "description": description, "url": url,
             "inLanguage": lang, "about": about},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": t(lang, "seo.breadcrumb_home"),
                 "item": base + localized_path(lang, "")},
                {"@type": "ListItem", "position": 2, "name": t(lang, "seo.breadcrumb_markets"),
                 "item": base + localized_path(lang, "markets")},
                {"@type": "ListItem", "position": 3, "name": market.name, "item": url},
            ]},
        ],
    })
    return page


async def _find_market(slug: str, lang: str):
    # Imported here: app.routers.market imports the app's routers and models,
    # which must not happen at import time of this low-level module.
    from app.routers.market import load_markets

    async with AsyncSessionLocal() as db:
        markets = await load_markets(db, lang)
    return next((m for m in markets if m.slug == slug.lower()), None)


# ── Rendering ────────────────────────────────────────────────────────────────

def _attr(value: str) -> str:
    return html.escape(value, quote=True)


def _json_ld(data: dict) -> str:
    # "</script>" inside a string would end the block early; < is the same character to a JSON parser.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def head_tags(page: Page, base: str) -> str:
    url = base + localized_path(page.lang, page.path)
    tags = [
        f"<title data-seo>{html.escape(page.title)}</title>",
        f'<meta data-seo name="description" content="{_attr(page.description)}">' if page.description else "",
    ]
    if page.noindex:
        tags.append('<meta data-seo name="robots" content="noindex, nofollow">')
    else:
        tags.append(f'<link data-seo rel="canonical" href="{_attr(url)}">')
        for lang in SUPPORTED_LANGUAGES:
            href = base + localized_path(lang, page.path)
            tags.append(f'<link data-seo rel="alternate" hreflang="{lang}" href="{_attr(href)}">')
        tags.append(
            f'<link data-seo rel="alternate" hreflang="x-default" '
            f'href="{_attr(base + localized_path(DEFAULT_LANGUAGE, page.path))}">'
        )
    tags += [
        f'<meta data-seo property="og:site_name" content="{SITE_NAME}">',
        '<meta data-seo property="og:type" content="website">',
        f'<meta data-seo property="og:title" content="{_attr(page.title)}">',
        f'<meta data-seo property="og:description" content="{_attr(page.description)}">',
        f'<meta data-seo property="og:url" content="{_attr(url)}">',
        f'<meta data-seo property="og:locale" content="{OG_LOCALES[page.lang]}">',
        *(f'<meta data-seo property="og:locale:alternate" content="{OG_LOCALES[lang]}">'
          for lang in SUPPORTED_LANGUAGES if lang != page.lang),
        '<meta data-seo name="twitter:card" content="summary">',
        *(f'<script data-seo type="application/ld+json">{_json_ld(item)}</script>' for item in page.json_ld),
    ]
    return "\n    ".join(tag for tag in tags if tag)


def render(template: str, page: Page, base: str) -> str:
    """index.html with the page's language and head. The template's own `data-seo` defaults are replaced."""
    document = _SEO_TAG.sub("", template)
    document = _HTML_LANG.sub(lambda m: f'<html{m.group(1)}lang="{page.lang}"', document, count=1)
    tags = head_tags(page, base)
    if HEAD_PLACEHOLDER in document:
        return document.replace(HEAD_PLACEHOLDER, tags, 1)
    return document.replace("</head>", f"    {tags}\n  </head>", 1)


_template_cache: dict[Path, str] = {}


def load_template(index_path: Path) -> str:
    if index_path not in _template_cache:
        _template_cache[index_path] = index_path.read_text(encoding="utf-8")
    return _template_cache[index_path]


async def render_spa_page(request: Request, index_path: Path, lang: str, path: str) -> tuple[str, int]:
    """The SPA shell for a client route, with its own head. Falls back to generic tags if the DB is down."""
    base = site_url(request)
    try:
        page = await resolve_page(lang, path, base)
    except Exception as e:
        logger.warning(f"Could not resolve page metadata for /{path} ({e}) — using the generic head")
        page = Page(200, lang, path, t(lang, "seo.home_title"), t(lang, "seo.home_description"))
    return render(load_template(index_path), page, base), page.status


# ── robots.txt / sitemap.xml ─────────────────────────────────────────────────

def robots_txt(base: str) -> str:
    # Private pages carry `noindex` instead of a Disallow line: a disallowed
    # page is never fetched, so its noindex would never be seen.
    return f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {base}/sitemap.xml\n"


def sitemap_xml(base: str, market_slugs: list[str]) -> str:
    paths = list(SITEMAP_PAGES) + [f"markets/{slug}" for slug in market_slugs]
    entries = []
    for path in paths:
        alternates = "".join(
            f'\n    <xhtml:link rel="alternate" hreflang="{lang}" href="{_attr(base + localized_path(lang, path))}"/>'
            for lang in SUPPORTED_LANGUAGES
        ) + (f'\n    <xhtml:link rel="alternate" hreflang="x-default" '
             f'href="{_attr(base + localized_path(DEFAULT_LANGUAGE, path))}"/>')
        for lang in SUPPORTED_LANGUAGES:
            entries.append(f"  <url>\n    <loc>{_attr(base + localized_path(lang, path))}</loc>{alternates}\n  </url>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(entries) + "\n</urlset>\n"
    )
