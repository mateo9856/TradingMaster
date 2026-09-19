import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.kafka import fx_rates as fx_module
from app.kafka.fx_rates import PEG_RATE, FxRates, watch_fx_rates
from app.metrics import fx_rate_fallback_total


class FakeClock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now


def fallback_count(quote: str) -> float:
    return fx_rate_fallback_total.labels(quote=quote)._value.get()


def test_usd_needs_no_conversion():
    assert FxRates().get("USD") == (Decimal("1.00000000"), "identity")


def test_fresh_live_rate_is_used():
    rates = FxRates(max_age_seconds=300, clock=FakeClock())
    rates.update("usdt", 0.9998)

    assert rates.get("USDT") == (Decimal("0.99980000"), "live")


def test_missing_rate_falls_back_to_peg_and_counts_it():
    rates = FxRates()
    before = fallback_count("USDC")

    assert rates.get("USDC") == (PEG_RATE, "peg")
    assert fallback_count("USDC") == before + 1


def test_stale_rate_falls_back_to_peg():
    clock = FakeClock()
    rates = FxRates(max_age_seconds=300, clock=clock)
    rates.update("USDT", "1.0003")

    clock.now += 301

    assert rates.get("USDT") == (PEG_RATE, "peg")


def test_new_rate_after_fallback_is_used_again():
    clock = FakeClock()
    rates = FxRates(max_age_seconds=300, clock=clock)
    assert rates.get("USDT")[1] == "peg"

    rates.update("USDT", "0.9995")

    assert rates.get("USDT") == (Decimal("0.99950000"), "live")


@pytest.mark.parametrize("quote", ["EUR", "BTC", ""])
def test_unknown_quote_raises(quote):
    with pytest.raises(ValueError, match="Unsupported quote currency"):
        FxRates().get(quote)


@pytest.mark.parametrize("quote, rate", [("EUR", 1.1), ("USD", 1), ("USDT", 0), ("USDT", -1), ("USDT", "abc")])
def test_update_rejects_invalid_quote_or_rate(quote, rate):
    with pytest.raises(ValueError):
        FxRates().update(quote, rate)


def _exchange(markets=("USDT/USD", "USDC/USD")):
    exchange = AsyncMock()
    exchange.id = "kraken"
    exchange.markets = {m: {} for m in markets}
    return exchange


async def test_watch_fx_rates_seeds_from_rest_then_streams_updates():
    rates = FxRates()
    exchange = _exchange(markets=("USDT/USD",))
    exchange.fetch_ticker.return_value = {"last": 0.9990}
    exchange.watch_ticker.side_effect = [{"last": 0.9997}, asyncio.CancelledError()]

    with pytest.raises(asyncio.CancelledError):
        await watch_fx_rates(rates, exchange=exchange, quotes=("USDT",))

    exchange.fetch_ticker.assert_awaited_once_with("USDT/USD")
    assert rates.get("USDT") == (Decimal("0.99970000"), "live")
    exchange.close.assert_awaited()


async def test_watch_fx_rates_uses_bid_ask_mid_without_last_price():
    rates = FxRates()
    exchange = _exchange(markets=("USDC/USD",))
    exchange.fetch_ticker.return_value = {"last": None, "bid": "0.9998", "ask": "1.0000"}
    exchange.watch_ticker.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await watch_fx_rates(rates, exchange=exchange, quotes=("USDC",))

    assert rates.get("USDC") == (Decimal("0.99990000"), "live")


async def test_watch_fx_rates_ignores_ticker_without_price():
    rates = FxRates()
    exchange = _exchange(markets=("USDT/USD",))
    exchange.fetch_ticker.return_value = {"last": None, "bid": None, "ask": None}
    exchange.watch_ticker.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await watch_fx_rates(rates, exchange=exchange, quotes=("USDT",))

    assert rates.get("USDT")[1] == "peg"


async def test_watch_fx_rates_reconnects_after_error():
    rates = FxRates()
    exchange = _exchange(markets=("USDT/USD",))
    exchange.fetch_ticker.side_effect = [RuntimeError("network down"), {"last": 1.0001}]
    exchange.watch_ticker.side_effect = asyncio.CancelledError()

    with patch.object(fx_module.asyncio, "sleep", new_callable=AsyncMock) as sleep:
        with pytest.raises(asyncio.CancelledError):
            await watch_fx_rates(rates, exchange=exchange, quotes=("USDT",))

    sleep.assert_awaited_once_with(5)
    assert exchange.load_markets.await_count == 2
    assert rates.get("USDT") == (Decimal("1.00010000"), "live")


async def test_watch_fx_rates_stops_when_exchange_lists_no_fx_market():
    exchange = _exchange(markets=())

    await watch_fx_rates(FxRates(), exchange=exchange, quotes=("USDT", "USDC"))

    exchange.fetch_ticker.assert_not_awaited()
    exchange.close.assert_awaited_once()
