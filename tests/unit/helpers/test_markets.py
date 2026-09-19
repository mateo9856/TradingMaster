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


@pytest.mark.parametrize("symbol", ["ETH/BTC", "BTC/EUR", "ETHBTC", "INVALID"])
def test_non_usd_quotes_are_rejected(symbol):
    with pytest.raises(ValueError, match="Unsupported quote currency"):
        unified_ticker(symbol)


@pytest.mark.parametrize("symbol", ["", "   ", None, "/USD", "USD", "BTC/USDT:USDT", "BT C/USD", "A/B/C"])
def test_malformed_symbols_are_rejected(symbol):
    with pytest.raises(ValueError):
        split_symbol(symbol)
