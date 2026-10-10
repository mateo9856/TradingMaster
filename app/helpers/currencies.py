"""Display currencies for the unified market feed.

Storage and Kafka stay in USD (see app/helpers/markets.py). A reader can ask
for prices in any currency the European Central Bank publishes a daily
reference rate for; the API converts on the way out with the rate for each
candle's own date (app/fiat/rates.py), so a candle from last month shows in PLN
at last month's rate, not today's.

Rates are stored as *units of the currency per 1 USD* ("units_per_usd"):
PLN 3.91 means 1 USD = 3.91 PLN. USD is always 1.
"""

from bisect import bisect_right
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

from app.helpers.prices import format_decimal, to_decimal

BASE_CURRENCY = "USD"

# The ECB reference-rate set (plus EUR, the ECB's own base), with English names.
# BGN is gone: Bulgaria adopted the euro on 2026-01-01 and the ECB stopped
# publishing it.
FIAT_CURRENCIES: dict[str, str] = {
    "USD": "US dollar",
    "EUR": "Euro",
    "PLN": "Polish złoty",
    "NOK": "Norwegian krone",
    "SEK": "Swedish krona",
    "DKK": "Danish krone",
    "ISK": "Icelandic króna",
    "CZK": "Czech koruna",
    "HUF": "Hungarian forint",
    "RON": "Romanian leu",
    "CHF": "Swiss franc",
    "GBP": "Pound sterling",
    "TRY": "Turkish lira",
    "JPY": "Japanese yen",
    "CNY": "Chinese yuan",
    "HKD": "Hong Kong dollar",
    "KRW": "South Korean won",
    "SGD": "Singapore dollar",
    "INR": "Indian rupee",
    "IDR": "Indonesian rupiah",
    "MYR": "Malaysian ringgit",
    "PHP": "Philippine peso",
    "THB": "Thai baht",
    "ILS": "Israeli shekel",
    "ZAR": "South African rand",
    "AUD": "Australian dollar",
    "NZD": "New Zealand dollar",
    "CAD": "Canadian dollar",
    "MXN": "Mexican peso",
    "BRL": "Brazilian real",
}

ONE = Decimal(1)


def validate_currency(code: str) -> str:
    """Upper-cased currency code, or ValueError if no rate is published for it."""
    if not isinstance(code, str):
        raise ValueError("Currency must be a three-letter code")
    upper = code.strip().upper()
    if upper not in FIAT_CURRENCIES:
        raise ValueError(f"Unsupported currency '{code}' — supported: {', '.join(FIAT_CURRENCIES)}")
    return upper


def usd_to(amount, units_per_usd) -> Decimal:
    """A USD amount in the target currency."""
    return to_decimal(to_decimal(amount) * to_decimal(units_per_usd))


def to_usd(amount, units_per_usd) -> Decimal:
    """An amount in some currency, in USD. Raises ValueError for a non-positive rate."""
    rate = to_decimal(units_per_usd)
    if rate <= 0:
        raise ValueError(f"Rate must be positive, got {units_per_usd!r}")
    return to_decimal(to_decimal(amount) / rate)


def usd_per_unit(units_per_usd) -> Decimal:
    """The multiplier that turns an amount in the currency into USD (the feed's fx_rate)."""
    rate = to_decimal(units_per_usd)
    if rate <= 0:
        raise ValueError(f"Rate must be positive, got {units_per_usd!r}")
    return to_decimal(ONE / rate)


def rate_on(rates: Sequence[tuple[date, Decimal]], day: date) -> Optional[tuple[date, Decimal]]:
    """
    The latest (rate_date, units_per_usd) on or before `day`, from `rates`
    sorted by date. The ECB publishes nothing on weekends and TARGET holidays,
    so Saturday uses Friday's rate. None if every rate is later than `day`.
    """
    index = bisect_right(rates, day, key=lambda entry: entry[0])
    return rates[index - 1] if index else None


PRICE_FIELDS: tuple[str, ...] = ("open_price", "high_price", "low_price", "close_price")


def convert_payload(payload: dict, currency: str, rate_date: Optional[date], units_per_usd) -> dict:
    """
    A copy of a unified-feed candle (a Kafka/WS message, prices as strings)
    with its prices in `currency`. The input is shared between subscribers and
    must not be changed. Volume is in base units and stays as it is.
    """
    converted = dict(payload)
    for field in PRICE_FIELDS:
        if field in converted:
            converted[field] = format_decimal(usd_to(converted[field], units_per_usd))
    converted["quote_currency"] = currency
    converted["currency_rate"] = format_decimal(units_per_usd)
    converted["rate_date"] = rate_date.isoformat() if rate_date else None
    return converted
