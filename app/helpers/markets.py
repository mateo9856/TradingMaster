"""Market (trading pair) naming for the unified market feed.

Exchanges quote the same coin in different dollar currencies — Binance and
Kraken mostly in USDT, Coinbase in USD. The unified feed publishes every price
in USD, so each exchange market maps to one *unified ticker* `BASE/USD`:

    BTC/USDT (binance) ─┐
    BTC/USD  (coinbase) ─┼─► BTC/USD
    BTC/USDC (kraken)   ─┘

Only USD-equivalent quote currencies are supported; they're converted to USD
by the producer (see app/kafka/fx_rates.py).
"""

import re

UNIFIED_QUOTE: str = "USD"

# Longest first, so the separator-less "BTCUSDT" splits as BTC + USDT, not BTCUSD + T.
USD_EQUIVALENT_QUOTES: tuple[str, ...] = ("USDT", "USDC", "USD")

# When one exchange lists several markets for the same coin, the one that feeds
# the unified ticker is picked in this order (native USD first, no conversion).
QUOTE_PREFERENCE: tuple[str, ...] = ("USD", "USDT", "USDC")

_SEPARATORS = re.compile(r"[/\-_:]")
_BASE_PATTERN = re.compile(r"^[A-Z0-9]+$")


def split_symbol(symbol: str) -> tuple[str, str]:
    """
    Splits a market symbol into (base, quote), upper-cased.

    Accepts "BTC/USDT", "btc-usdt", "BTC_USDT" and the separator-less
    "BTCUSDT" (split on a known USD-equivalent quote suffix). Raises
    ValueError for anything that isn't a BASE/QUOTE pair with a USD-equivalent
    quote currency.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("Market symbol must be a non-empty string")

    text = symbol.strip().upper()
    parts = _SEPARATORS.split(text)

    if len(parts) == 2:
        base, quote = parts
    elif len(parts) == 1:
        quote = next((q for q in USD_EQUIVALENT_QUOTES if text.endswith(q)), None)
        if quote is None:
            raise ValueError(
                f"Unsupported quote currency in '{symbol}' — supported: {', '.join(USD_EQUIVALENT_QUOTES)}"
            )
        base = text[: -len(quote)]
    else:
        raise ValueError(f"Invalid market symbol '{symbol}'")

    if not base or not _BASE_PATTERN.match(base):
        raise ValueError(f"Invalid market symbol '{symbol}' — missing base currency")
    if quote not in USD_EQUIVALENT_QUOTES:
        raise ValueError(
            f"Unsupported quote currency in '{symbol}' — supported: {', '.join(USD_EQUIVALENT_QUOTES)}"
        )
    return base, quote


def unified_ticker(symbol: str) -> str:
    """Unified-feed ticker for any spelling of a USD-equivalent market, e.g. "BTC/USD"."""
    base, _ = split_symbol(symbol)
    return f"{base}/{UNIFIED_QUOTE}"


def topic_ticker(symbol: str) -> str:
    """Kafka topic segment for a market — the unified ticker without separator, e.g. "BTCUSD"."""
    return unified_ticker(symbol).replace("/", "")
