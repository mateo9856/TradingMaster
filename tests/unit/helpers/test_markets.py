import pytest

from app.helpers.markets import split_symbol, topic_ticker, unified_ticker


@pytest.mark.parametrize("symbol, expected", [
    ("BTC/USDT", ("BTC", "USDT")),
    ("btc-usdt", ("BTC", "USDT")),
    ("BTC_USDC", ("BTC", "USDC")),
    ("BTCUSDT", ("BTC", "USDT")),
    ("BTCUSDC", ("BTC", "USDC")),
    ("BTCUSD", ("BTC", "USD")),
    (" eth/usd ", ("ETH", "USD")),
    ("1INCH/USDT", ("1INCH", "USDT")),
])
def test_split_symbol_accepts_every_spelling(symbol, expected):
    assert split_symbol(symbol) == expected


@pytest.mark.parametrize("symbol", ["BTC/USDT", "btc-usdt", "BTCUSDT", "BTC/USD", "BTC/USDC", "btcusdc"])
def test_every_usd_equivalent_market_maps_to_one_unified_ticker(symbol):
    assert unified_ticker(symbol) == "BTC/USD"


def test_topic_ticker_uses_the_unified_ticker():
    assert topic_ticker("BTC/USDT") == "BTCUSD"
    assert topic_ticker("eth-usd") == "ETHUSD"


@pytest.mark.parametrize("symbol, expected", [
    ("BTC/EUR", "BTC/USD"),
    ("btc-pln", "BTC/USD"),
    ("PKN.WA/PLN", "PKN.WA/USD"),
    ("eqnr.ol/nok", "EQNR.OL/USD"),
    ("AAPL/USD", "AAPL/USD"),
])
def test_fiat_quoted_and_stock_markets_map_to_a_usd_unified_ticker(symbol, expected):
    assert unified_ticker(symbol) == expected


def test_stock_topic_segment_is_alphanumeric():
    assert topic_ticker("PKN.WA/PLN") == "PKNWAUSD"


def test_separator_less_symbols_only_split_on_usd_equivalent_quotes():
    # The WebSocket path sends "PKN.WAUSD" — the venue suffix survives.
    assert split_symbol("PKN.WAUSD") == ("PKN.WA", "USD")
    with pytest.raises(ValueError, match="Unsupported quote currency"):
        split_symbol("BTCPLN")


@pytest.mark.parametrize("symbol", ["ETH/BTC", "BTC/XYZ", "ETHBTC", "INVALID"])
def test_unsupported_quotes_are_rejected(symbol):
    with pytest.raises(ValueError, match="Unsupported quote currency"):
        unified_ticker(symbol)


@pytest.mark.parametrize("symbol", ["", "   ", None, "/USD", "USD", "BTC/USDT:USDT", "BT C/USD", "A/B/C",
                                    "PKN.WA.X/PLN", "PKN./PLN", ".WA/PLN"])
def test_malformed_symbols_are_rejected(symbol):
    with pytest.raises(ValueError):
        split_symbol(symbol)
