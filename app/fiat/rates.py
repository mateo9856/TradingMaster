"""
ECB daily reference rates → `fiat_rates`, and an in-process cache over them.

The European Central Bank publishes one euro reference rate per currency each
working day, around 16:00 CET. They are free, keyless and official, which is
why they back every non-USD price in the platform:

  - the API converts stored USD prices to the reader's currency on the way out,
    with the rate for each candle's own date (see app/helpers/currencies.py);
  - the producer converts fiat-quoted markets (a Warsaw stock in PLN) to USD on
    the way in, with the same rate — so it reads back as the quoted price.

Rates are reference rates, not tradeable quotes: a day's conversion uses one
number for the whole day. That is the right trade-off for display, and the
response says which date's rate was applied.

The ECB file is EUR-based; rows are stored as units per 1 USD
(X per USD = X per EUR ÷ USD per EUR). Insertion ignores duplicates, so every
API replica running the fetcher is harmless.
"""

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Iterable, Optional

import httpx
from defusedxml import ElementTree
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ECB_DAILY_URL, ECB_HISTORY_URL, FIAT_CACHE_SECONDS, FIAT_RATES_REFRESH_SECONDS
from app.helpers.currencies import BASE_CURRENCY, FIAT_CURRENCIES, ONE, rate_on
from app.helpers.prices import to_decimal
from app.helpers.upsert import insert_ignore_duplicates
from app.metrics import fiat_rates_fetch_total, fiat_rates_latest_date_seconds
from app.models.database import AsyncSessionLocal
from app.models.fiat_rate import FiatRate

logger = logging.getLogger(__name__)

_ECB_NS = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"
_RETRY_SECONDS = 300
_HTTP_TIMEOUT_SECONDS = 20
# Days of rates the in-process cache holds: the stock poller asks for at most
# a few days back, and the WebSocket only for today.
CACHE_WINDOW_DAYS = 30


# ── ECB file ─────────────────────────────────────────────────────────────────

def parse_ecb_xml(content: bytes | str) -> dict[date, dict[str, Decimal]]:
    """
    {date: {currency: units per EUR}} from an ECB eurofxref XML document
    (daily or history). Unknown currencies and malformed rates are skipped.
    """
    root = ElementTree.fromstring(content)
    by_date: dict[date, dict[str, Decimal]] = {}
    for day_cube in root.iter(f"{_ECB_NS}Cube"):
        stamp = day_cube.get("time")
        if not stamp:
            continue
        day = date.fromisoformat(stamp)
        rates: dict[str, Decimal] = {}
        for cube in day_cube:
            currency, rate = cube.get("currency"), cube.get("rate")
            if currency not in FIAT_CURRENCIES:
                continue
            try:
                value = Decimal(rate)
            except (InvalidOperation, TypeError):
                logger.warning(f"ECB rate for {currency} on {day} is not a number: {rate!r}")
                continue
            if value > 0:
                rates[currency] = value
        if rates:
            by_date[day] = rates
    return by_date


def usd_crosses(per_eur: dict[str, Decimal]) -> dict[str, Decimal]:
    """
    Units per 1 USD from units per 1 EUR. Empty without a USD rate — there is
    nothing to cross through. USD itself is implicit (always 1) and not stored.
    """
    usd_per_eur = per_eur.get(BASE_CURRENCY)
    if not usd_per_eur:
        return {}
    crosses = {"EUR": to_decimal(ONE / usd_per_eur)}
    for currency, units_per_eur in per_eur.items():
        if currency != BASE_CURRENCY:
            crosses[currency] = to_decimal(units_per_eur / usd_per_eur)
    return crosses


def to_rows(by_date: dict[date, dict[str, Decimal]]) -> list[dict]:
    rows = []
    for day, per_eur in by_date.items():
        for currency, units_per_usd in usd_crosses(per_eur).items():
            rows.append({"rate_date": day, "currency": currency, "units_per_usd": units_per_usd})
    return rows


async def store_rates(session: AsyncSession, by_date: dict[date, dict[str, Decimal]]) -> int:
    """Inserts the rates, skipping days already stored. Returns the number of new rows. Commits."""
    inserted = await insert_ignore_duplicates(session, FiatRate, to_rows(by_date), ["rate_date", "currency"])
    await session.commit()
    return inserted


async def fetch_ecb(url: str, client: httpx.AsyncClient) -> dict[date, dict[str, Decimal]]:
    response = await client.get(url, timeout=_HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    return parse_ecb_xml(response.content)


async def update_once(url: str, client: httpx.AsyncClient, session_factory=AsyncSessionLocal) -> int:
    by_date = await fetch_ecb(url, client)
    async with session_factory() as session:
        inserted = await store_rates(session, by_date)
    if by_date:
        newest = max(by_date)
        fiat_rates_latest_date_seconds.set(
            datetime(newest.year, newest.month, newest.day, tzinfo=timezone.utc).timestamp()
        )
    return inserted


async def watch_fiat_rates(
    cache: Optional["FiatRateCache"] = None,
    client: Optional[httpx.AsyncClient] = None,
    session_factory=AsyncSessionLocal,
) -> None:
    """
    Backfills ~90 days from the ECB history file, then fetches the daily file
    every FIAT_RATES_REFRESH_SECONDS. Never raises (except on cancellation):
    a failed download is logged and retried, and conversion keeps using the
    last rate it has.
    """
    own_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=True)
    url = ECB_HISTORY_URL
    try:
        while True:
            try:
                inserted = await update_once(url, client, session_factory)
                fiat_rates_fetch_total.labels(outcome="success").inc()
                logger.info(f"ECB reference rates updated ({inserted} new row(s))")
                if cache is not None:
                    await cache.refresh(session_factory)
                url = ECB_DAILY_URL
                delay = FIAT_RATES_REFRESH_SECONDS
            except asyncio.CancelledError:
                raise
            except Exception as e:
                fiat_rates_fetch_total.labels(outcome="failure").inc()
                logger.warning(f"ECB reference rates update failed: {e} — retrying in {_RETRY_SECONDS}s")
                delay = _RETRY_SECONDS
            await asyncio.sleep(delay)
    finally:
        if own_client:
            await client.aclose()


# ── Lookup ───────────────────────────────────────────────────────────────────

async def load_series(
    session: AsyncSession, currency: str, start: date, end: date,
) -> list[tuple[date, Decimal]]:
    """
    Sorted (rate_date, units_per_usd) covering start..end for one currency,
    including the last rate before `start` so a Monday-morning or holiday
    candle still has one. Empty for USD (no conversion) or when no rate exists.
    """
    if currency == BASE_CURRENCY:
        return []
    floor = await session.scalar(
        select(func.max(FiatRate.rate_date))
        .where(FiatRate.currency == currency, FiatRate.rate_date <= start)
    )
    result = await session.execute(
        select(FiatRate.rate_date, FiatRate.units_per_usd)
        .where(FiatRate.currency == currency)
        .where(FiatRate.rate_date >= (floor or start), FiatRate.rate_date <= end)
        .order_by(FiatRate.rate_date)
    )
    return [(day, Decimal(rate)) for day, rate in result.all()]


async def latest_rates(session: AsyncSession) -> dict[str, tuple[date, Decimal]]:
    """{currency: (rate_date, units_per_usd)} for each currency's newest rate."""
    newest = (
        select(FiatRate.currency, func.max(FiatRate.rate_date).label("rate_date"))
        .group_by(FiatRate.currency)
        .subquery()
    )
    result = await session.execute(
        select(FiatRate.currency, FiatRate.rate_date, FiatRate.units_per_usd)
        .join(newest, (FiatRate.currency == newest.c.currency) & (FiatRate.rate_date == newest.c.rate_date))
    )
    return {currency: (day, Decimal(rate)) for currency, day, rate in result.all()}


class FiatRateCache:
    """
    The last CACHE_WINDOW_DAYS of rates, held in memory for the hot paths — a
    WebSocket frame and a produced candle can't afford a query each. Reloads
    from the database at most every FIAT_CACHE_SECONDS, so a process that
    doesn't run the fetcher itself (producer_runner next to the API) still
    sees new rates.
    """

    def __init__(self, ttl_seconds: float = FIAT_CACHE_SECONDS, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._loaded_at: Optional[float] = None
        self._series: dict[str, list[tuple[date, Decimal]]] = {}
        self._lock = asyncio.Lock()

    def load(self, rows: Iterable[tuple[str, date, Decimal]]) -> None:
        """Replaces the cached rates (used by refresh, and directly by tests)."""
        series: dict[str, list[tuple[date, Decimal]]] = {}
        for currency, day, rate in rows:
            series.setdefault(currency, []).append((day, Decimal(rate)))
        for entries in series.values():
            entries.sort(key=lambda entry: entry[0])
        self._series = series
        self._loaded_at = self._clock()

    async def refresh(self, session_factory=AsyncSessionLocal) -> None:
        since = datetime.now(timezone.utc).date() - timedelta(days=CACHE_WINDOW_DAYS)
        async with session_factory() as session:
            result = await session.execute(
                select(FiatRate.currency, FiatRate.rate_date, FiatRate.units_per_usd)
                .where(FiatRate.rate_date >= since)
            )
            self.load(result.all())

    async def ensure_fresh(self, session_factory=AsyncSessionLocal) -> None:
        if self._loaded_at is not None and self._clock() - self._loaded_at < self._ttl:
            return
        async with self._lock:
            if self._loaded_at is not None and self._clock() - self._loaded_at < self._ttl:
                return
            try:
                await self.refresh(session_factory)
            except Exception as e:
                # Keep converting with what we have; try again next TTL.
                self._loaded_at = self._clock()
                logger.warning(f"Could not reload fiat rates ({e}) — using the cached ones")

    def lookup(self, currency: str, day: date) -> Optional[tuple[date, Decimal]]:
        """
        (rate_date, units_per_usd) for `currency` on `day`. None for USD (there
        is nothing to convert) and for a currency with no rate on or before `day`.
        """
        if currency == BASE_CURRENCY:
            return None
        return rate_on(self._series.get(currency, []), day)


# Shared by the producer (fiat-quoted markets → USD) and the WebSocket (USD → reader's currency).
fiat_rates = FiatRateCache()
