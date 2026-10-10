from datetime import date
from decimal import Decimal

import pytest

from app.helpers.currencies import (
    FIAT_CURRENCIES,
    convert_payload,
    rate_on,
    to_usd,
    usd_per_unit,
    usd_to,
    validate_currency,
)

RATES = [(date(2026, 6, 19), Decimal("4.0")), (date(2026, 6, 22), Decimal("3.5"))]


@pytest.mark.parametrize("code", ["PLN", "pln", " eur ", "NOK", "USD"])
def test_validate_currency_accepts_ecb_currencies(code):
    assert validate_currency(code) == code.strip().upper()


@pytest.mark.parametrize("code", ["XYZ", "", "USDT", None, "PLNX"])
def test_validate_currency_rejects_anything_else(code):
    with pytest.raises(ValueError):
        validate_currency(code)


def test_the_list_covers_the_currencies_users_asked_for():
    assert {"USD", "EUR", "PLN", "NOK", "SEK", "GBP", "CHF", "CZK"} <= set(FIAT_CURRENCIES)


def test_conversion_both_ways_round_trips_at_8_decimals():
    assert usd_to("100", "3.91175263") == Decimal("391.17526300")
    assert to_usd("60.50", "3.91175263") == Decimal("15.46621316")
    assert usd_to(to_usd("60.50", "3.91175263"), "3.91175263").quantize(Decimal("0.0001")) == Decimal("60.5000")


def test_usd_per_unit_is_the_inverse_rate():
    assert usd_per_unit("4") == Decimal("0.25000000")
    with pytest.raises(ValueError):
        usd_per_unit("0")


@pytest.mark.parametrize("day, expected", [
    (date(2026, 6, 19), date(2026, 6, 19)),
    (date(2026, 6, 20), date(2026, 6, 19)),     # Saturday → Friday's rate
    (date(2026, 6, 22), date(2026, 6, 22)),
    (date(2026, 7, 1), date(2026, 6, 22)),      # newer than every rate → the latest
])
def test_rate_on_uses_the_latest_rate_on_or_before_the_day(day, expected):
    assert rate_on(RATES, day)[0] == expected


def test_rate_on_is_none_before_the_first_rate():
    assert rate_on(RATES, date(2026, 1, 1)) is None
    assert rate_on([], date(2026, 1, 1)) is None


def test_convert_payload_copies_and_converts_prices_only():
    payload = {"open_price": "10.00000000", "high_price": "12.00000000", "low_price": "9.00000000",
               "close_price": "11.00000000", "volume": "5.00000000", "quote_currency": "USD"}

    converted = convert_payload(payload, "PLN", date(2026, 6, 22), Decimal("3.5"))

    assert converted["close_price"] == "38.50000000"
    assert converted["volume"] == "5.00000000"
    assert converted["quote_currency"] == "PLN"
    assert converted["currency_rate"] == "3.50000000"
    assert converted["rate_date"] == "2026-06-22"
    assert payload["close_price"] == "11.00000000"
