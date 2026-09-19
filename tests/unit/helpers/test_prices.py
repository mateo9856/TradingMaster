from decimal import Decimal

import pytest

from app.helpers.prices import PRICE_SCALE, format_decimal, to_decimal


@pytest.mark.parametrize("value", [65000.1, "65000.1", "65000.10000000", Decimal("65000.1"), " 65000.1 "])
def test_every_input_type_gives_the_same_format(value):
    assert format_decimal(value) == "65000.10000000"


def test_integers_get_fixed_decimal_places():
    assert format_decimal(3) == "3.00000000"
    assert format_decimal(0) == "0.00000000"


def test_float_noise_is_not_carried_into_the_price():
    assert format_decimal(0.1 + 0.2) == "0.30000000"


def test_to_decimal_quantizes_to_price_scale():
    value = to_decimal("1.123456789")
    assert value == Decimal("1.12345679")
    assert value.as_tuple().exponent == -PRICE_SCALE


def test_rounding_is_half_even():
    assert format_decimal("0.000000005") == "0.00000000"
    assert format_decimal("0.000000015") == "0.00000002"


def test_small_prices_keep_their_digits():
    assert format_decimal(0.00001234) == "0.00001234"


@pytest.mark.parametrize("value", [None, "abc", "", float("nan"), float("inf"), "-Infinity", True, [], object()])
def test_invalid_values_raise(value):
    with pytest.raises(ValueError, match="Invalid price value"):
        to_decimal(value)


@pytest.mark.parametrize("value", [-1, -0.01, "-5"])
def test_negative_values_raise(value):
    with pytest.raises(ValueError, match="must not be negative"):
        to_decimal(value)
