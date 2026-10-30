from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.helpers.time import utc_now_naive
from app.trading import quotes
from app.trading.quotes import (
    MarketSource,
    PriceQuote,
    QuoteService,
    QuoteUnavailable,
    validate_quote,
)


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
    fetch.side_effect = TimeoutError("network failed")
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
    if case == "missing_bid":
        info.pop("bid")
    if case == "closed":
        info["marketState"] = "CLOSED"
    if case == "missing_time":
        info.pop("regularMarketTime")
    if case == "wrong_currency":
        info["currency"] = "EUR"
    if case == "missing_session":
        metadata = {}
    monkeypatch.setattr(yf, "Ticker", lambda symbol: SimpleNamespace(get_info=lambda: info, get_history_metadata=lambda: metadata))
    source = MarketSource("yahoo", "PKN.WA/USD", "PKN.WA/PLN", "stock")
    if case == "valid":
        result = quotes.fetch_stock(source)
        assert result.bid == Decimal(99) and result.delayed
        validate_quote(result)
    else:
        with pytest.raises((QuoteUnavailable, ValueError)):
            quotes.fetch_stock(source)


@pytest.mark.parametrize("error", [RuntimeError("bug"), TypeError("bug"), AttributeError("bug")])
async def test_unexpected_provider_errors_propagate(monkeypatch, error):
    monkeypatch.setattr(quotes, "fetch_crypto", AsyncMock(side_effect=error))
    with pytest.raises(type(error), match="bug"):
        await QuoteService().get(None, MarketSource("kraken", "BTC/USD", "BTC/USD", "crypto"))


async def test_database_errors_during_fx_resolution_propagate(monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    now = utc_now_naive()
    monkeypatch.setattr(quotes, "fetch_crypto", AsyncMock(return_value=PriceQuote(Decimal(1), Decimal(2), now, now)))
    monkeypatch.setattr(quotes, "usd_rate", AsyncMock(side_effect=SQLAlchemyError("database failed")))
    with pytest.raises(SQLAlchemyError, match="database failed"):
        await QuoteService().get(None, MarketSource("kraken", "BTC/USD", "BTC/USDT", "crypto"))


async def test_quote_cancellation_propagates_and_closes_client(monkeypatch):
    import asyncio

    exchange = SimpleNamespace(fetch_order_book=AsyncMock(side_effect=asyncio.CancelledError), close=AsyncMock())
    monkeypatch.setattr(quotes.ccxt, "kraken", Mock(return_value=exchange))
    with pytest.raises(asyncio.CancelledError):
        await QuoteService().get(None, MarketSource("kraken", "BTC/USD", "BTC/USD", "crypto"))
    exchange.close.assert_awaited_once()


@pytest.mark.parametrize("error", [quotes.ccxt.NetworkError("offline"), quotes.ccxt.ExchangeError("unavailable"), TimeoutError()])
async def test_expected_crypto_provider_failures_are_unavailable(monkeypatch, error):
    exchange = SimpleNamespace(fetch_order_book=AsyncMock(side_effect=error), close=AsyncMock())
    monkeypatch.setattr(quotes.ccxt, "kraken", Mock(return_value=exchange))
    with pytest.raises(QuoteUnavailable, match="provider"):
        await quotes.fetch_crypto(MarketSource("kraken", "BTC/USD", "BTC/USD", "crypto"))
    exchange.close.assert_awaited_once()


@pytest.mark.parametrize("book", [None, [], {"bids": [[]], "asks": [[2]]},
    {"bids": [["oops"]], "asks": [[2]]}, {"bids": [[1]], "asks": [[2]], "timestamp": "bad"}])
def test_malformed_crypto_payload_is_unavailable(book):
    with pytest.raises(QuoteUnavailable):
        quotes.parse_crypto_book(book)


@pytest.mark.parametrize("error_kind", ["network", "provider", "unexpected"])
def test_stock_provider_failure_boundary(monkeypatch, error_kind):
    import yfinance as yf
    from curl_cffi.requests.exceptions import ConnectionError
    from yfinance.exceptions import YFRateLimitError

    error = {"network": ConnectionError("offline"), "provider": YFRateLimitError(),
             "unexpected": RuntimeError("programming error")}[error_kind]
    monkeypatch.setattr(yf, "Ticker", lambda symbol: SimpleNamespace(get_info=Mock(side_effect=error)))
    with pytest.raises(RuntimeError if error_kind == "unexpected" else QuoteUnavailable):
        quotes.fetch_stock(MarketSource("yahoo", "PKN.WA/USD", "PKN.WA/PLN", "stock"))


async def test_resolved_quote_never_accesses_the_session(monkeypatch):
    now = utc_now_naive()
    monkeypatch.setattr(quotes, "fetch_crypto", AsyncMock(return_value=PriceQuote(Decimal(1), Decimal(2), now, now)))
    rate = AsyncMock(side_effect=AssertionError("FX was already resolved"))
    monkeypatch.setattr(quotes, "usd_rate", rate)
    price, fx = await QuoteService().get(None, MarketSource("kraken", "BTC/USD", "BTC/USDT", "crypto"),
                                       conversion_rate=Decimal("0.9"))
    assert price.ask == Decimal("1.80000000") and fx == Decimal("0.9")
    rate.assert_not_awaited()


async def test_expected_cleanup_failure_does_not_replace_cancellation(monkeypatch):
    import asyncio

    exchange = SimpleNamespace(fetch_order_book=AsyncMock(side_effect=asyncio.CancelledError),
                               close=AsyncMock(side_effect=quotes.ccxt.NetworkError("cleanup failed")))
    monkeypatch.setattr(quotes.ccxt, "kraken", Mock(return_value=exchange))
    with pytest.raises(asyncio.CancelledError):
        await quotes.fetch_crypto(MarketSource("kraken", "BTC/USD", "BTC/USD", "crypto"))
