from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.helpers.time import utc_now_naive
from app.trading import quotes
from app.trading.quotes import MarketSource, PriceQuote, QuoteService, QuoteUnavailable, validate_quote


@pytest.mark.parametrize("bid,ask", [("0", "100"), ("100", "99"), ("NaN", "1"), ("1", "Infinity")])
def test_invalid_bid_ask(bid, ask):
    now = utc_now_naive()
    with pytest.raises(QuoteUnavailable):
        validate_quote(PriceQuote(Decimal(bid), Decimal(ask), now, now))


def test_quote_freshness_and_missing_exchange_timestamp():
    now = utc_now_naive()
    validate_quote(PriceQuote(Decimal(1), Decimal(2), None, now), now)
    with pytest.raises(QuoteUnavailable, match="stale"):
        validate_quote(PriceQuote(Decimal(1), Decimal(2), now - timedelta(seconds=31), now), now)
    with pytest.raises(QuoteUnavailable, match="stale"):
        validate_quote(PriceQuote(Decimal(1), Decimal(2), now, now - timedelta(seconds=16)), now)


def test_stocks_require_source_time_open_session_and_max_age():
    now = utc_now_naive()
    def quote(source=now, end=now + timedelta(minutes=10)):
        return PriceQuote(Decimal(1), Decimal(2), source, now, True, end)
    validate_quote(quote(now - timedelta(minutes=15)), now)
    for snapshot in [quote(None), quote(end=now), quote(now - timedelta(minutes=21)), quote(end=None)]:
        with pytest.raises(QuoteUnavailable):
            validate_quote(snapshot, now)


async def test_crypto_orderbook_and_client_cleanup(monkeypatch):
    exchange = SimpleNamespace(fetch_order_book=AsyncMock(return_value={"bids": [[99, 1]], "asks": [[100, 1]], "timestamp": None}),
                               close=AsyncMock())
    monkeypatch.setattr(quotes.ccxt, "kraken", Mock(return_value=exchange))
    source = MarketSource("kraken", "BTC/USD", "BTC/USD", "crypto")
    price = await quotes.fetch_crypto(source)
    assert price.bid == Decimal(99) and price.ask == Decimal(100)
    assert price.source_at is None
    exchange.close.assert_awaited_once()
    exchange.fetch_order_book.return_value = {"bids": [], "asks": []}
    with pytest.raises(QuoteUnavailable):
        await quotes.fetch_crypto(source)
    assert exchange.close.await_count == 2


async def test_provider_conversion_caching_and_errors(monkeypatch):
    now = utc_now_naive()
    fetch = AsyncMock(return_value=PriceQuote(Decimal(99), Decimal(100), now, now))
    monkeypatch.setattr(quotes, "fetch_crypto", fetch)
    monkeypatch.setattr(quotes, "usd_rate", AsyncMock(return_value=Decimal("0.9")))
    service = QuoteService()
    source = MarketSource("kraken", "BTC/USD", "BTC/USDT", "crypto")
    first = await service.get(None, source)
    assert first[0].bid == Decimal("89.10000000")
    assert first[0].ask == Decimal("90.00000000")
    assert await service.get(None, source) == first
    fetch.assert_awaited_once()
    fetch.side_effect = RuntimeError("network failed")
    with pytest.raises(QuoteUnavailable, match="provider"):
        await QuoteService().get(None, source)


async def test_stablecoin_conversion_requires_valid_live_book(monkeypatch):
    monkeypatch.setattr(quotes, "fetch_crypto", AsyncMock(side_effect=QuoteUnavailable("missing FX book")))
    with pytest.raises(QuoteUnavailable):
        await quotes.usd_rate(None, "USDT")
    assert await quotes.usd_rate(None, "USD") == Decimal(1)


@pytest.mark.parametrize("case", ["valid", "missing_bid", "closed", "missing_time", "wrong_currency", "missing_session"])
def test_yahoo_stock_bidask_and_session_metadata(monkeypatch, case):
    import yfinance as yf
    now = utc_now_naive()
    epoch = (now - datetime(1970, 1, 1)).total_seconds()
    info = {"bid": 99, "ask": 100, "currency": "PLN", "regularMarketTime": epoch - 900, "marketState": "REGULAR"}
    metadata = {"currentTradingPeriod": {"regular": {"start": epoch - 3600, "end": epoch + 3600}}}
    if case == "missing_bid": info.pop("bid")
    if case == "closed": info["marketState"] = "CLOSED"
    if case == "missing_time": info.pop("regularMarketTime")
    if case == "wrong_currency": info["currency"] = "EUR"
    if case == "missing_session": metadata = {}
    monkeypatch.setattr(yf, "Ticker", lambda symbol: SimpleNamespace(get_info=lambda: info, get_history_metadata=lambda: metadata))
    source = MarketSource("yahoo", "PKN.WA/USD", "PKN.WA/PLN", "stock")
    if case == "valid":
        result = quotes.fetch_stock(source)
        assert result.bid == Decimal(99) and result.delayed
        validate_quote(result)
    else:
        with pytest.raises((QuoteUnavailable, ValueError)):
            quotes.fetch_stock(source)
