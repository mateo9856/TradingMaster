from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.fiat.rates import (
    FiatRateCache,
    latest_rates,
    load_series,
    parse_ecb_xml,
    store_rates,
    usd_crosses,
)
from app.models.fiat_rate import FiatRate

ECB_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube>
    <Cube time='2026-10-09'>
      <Cube currency='USD' rate='1.1206'/>
      <Cube currency='PLN' rate='4.3835'/>
      <Cube currency='NOK' rate='10.7155'/>
      <Cube currency='XXX' rate='1.0'/>
      <Cube currency='SEK' rate='n/a'/>
    </Cube>
    <Cube time='2026-10-08'>
      <Cube currency='USD' rate='1.1000'/>
      <Cube currency='PLN' rate='4.4000'/>
    </Cube>
  </Cube>
</gesmes:Envelope>"""


def test_parse_ecb_xml_reads_every_day_and_skips_unknown_or_broken_rates():
    by_date = parse_ecb_xml(ECB_XML)

    assert set(by_date) == {date(2026, 10, 9), date(2026, 10, 8)}
    assert by_date[date(2026, 10, 9)] == {
        "USD": Decimal("1.1206"), "PLN": Decimal("4.3835"), "NOK": Decimal("10.7155"),
    }


def test_parse_ecb_xml_refuses_entity_expansion():
    bomb = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><x>&b;</x>"""
    with pytest.raises(Exception):
        parse_ecb_xml(bomb)


def test_usd_crosses_go_through_the_euro():
    crosses = usd_crosses({"USD": Decimal("1.1206"), "PLN": Decimal("4.3835")})

    assert crosses["PLN"] == Decimal("3.91174371")     # 4.3835 / 1.1206
    assert crosses["EUR"] == Decimal("0.89237908")     # 1 / 1.1206
    assert "USD" not in crosses


def test_usd_crosses_need_a_usd_rate():
    assert usd_crosses({"PLN": Decimal("4.3835")}) == {}


async def test_store_rates_is_idempotent(db_session):
    by_date = parse_ecb_xml(ECB_XML)

    first = await store_rates(db_session, by_date)
    second = await store_rates(db_session, by_date)

    assert first == 5           # 2026-10-09: EUR, PLN, NOK; 2026-10-08: EUR, PLN
    assert second == 0
    rows = (await db_session.execute(select(FiatRate))).scalars().all()
    assert len(rows) == 5


async def test_load_series_includes_the_rate_before_the_window(db_session):
    await store_rates(db_session, parse_ecb_xml(ECB_XML))

    series = await load_series(db_session, "PLN", date(2026, 10, 9), date(2026, 10, 9))
    from_weekend = await load_series(db_session, "PLN", date(2026, 10, 10), date(2026, 10, 11))

    assert [d for d, _ in series] == [date(2026, 10, 9)]
    assert [d for d, _ in from_weekend] == [date(2026, 10, 9)]
    assert await load_series(db_session, "USD", date(2026, 10, 9), date(2026, 10, 9)) == []


async def test_latest_rates_returns_each_currencys_newest_rate(db_session):
    await store_rates(db_session, parse_ecb_xml(ECB_XML))

    latest = await latest_rates(db_session)

    assert latest["PLN"][0] == date(2026, 10, 9)
    assert latest["NOK"][0] == date(2026, 10, 9)


def test_cache_lookup_by_day():
    cache = FiatRateCache()
    cache.load([("PLN", date(2026, 10, 9), Decimal("3.9")), ("PLN", date(2026, 10, 8), Decimal("4.0"))])

    assert cache.lookup("PLN", date(2026, 10, 8)) == (date(2026, 10, 8), Decimal("4.0"))
    assert cache.lookup("PLN", date(2026, 10, 11)) == (date(2026, 10, 9), Decimal("3.9"))
    assert cache.lookup("PLN", date(2026, 10, 1)) is None
    assert cache.lookup("NOK", date(2026, 10, 9)) is None
    assert cache.lookup("USD", date(2026, 10, 9)) is None


async def test_cache_only_reloads_after_its_ttl():
    now = [0.0]
    cache = FiatRateCache(ttl_seconds=60, clock=lambda: now[0])
    calls = []

    async def refresh(_factory=None):
        calls.append(now[0])
        cache.load([])

    cache.refresh = refresh
    await cache.ensure_fresh()
    await cache.ensure_fresh()
    now[0] = 61
    await cache.ensure_fresh()

    assert calls == [0.0, 61]


async def test_cache_keeps_its_rates_when_the_reload_fails():
    cache = FiatRateCache(ttl_seconds=0)
    cache.load([("PLN", date(2026, 10, 9), Decimal("3.9"))])

    async def broken(_factory=None):
        raise RuntimeError("db down")

    cache.refresh = broken
    await cache.ensure_fresh()

    assert cache.lookup("PLN", date(2026, 10, 9)) is not None
