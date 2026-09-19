"""Price/volume number format for the unified market feed.

Every price and volume the platform publishes — Kafka, database, REST and
WebSocket — is an exact decimal with PRICE_SCALE digits after the point,
regardless of how the source exchange formatted it. Floats are converted via
their shortest string repr (Decimal(str(x))) so 0.1 stays 0.1 instead of
picking up binary floating-point noise.
"""

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

PRICE_SCALE: int = 8
_QUANTUM = Decimal(1).scaleb(-PRICE_SCALE)   # Decimal("0.00000001")


def to_decimal(value) -> Decimal:
    """
    Normalizes a price/volume to a non-negative Decimal with PRICE_SCALE places.
    Raises ValueError for None, booleans, non-numeric strings, NaN/infinity and
    negative values.
    """
    if value is None or isinstance(value, bool):
        raise ValueError(f"Invalid price value: {value!r}")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid price value: {value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"Invalid price value: {value!r}")
    if number < 0:
        raise ValueError(f"Price value must not be negative: {value!r}")
    return number.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


def format_decimal(value) -> str:
    """Formats a price/volume as a fixed-point string, e.g. "65000.10000000"."""
    return f"{to_decimal(value):.{PRICE_SCALE}f}"
