"""Stable trading wire values, also used by persisted idempotency results."""

from datetime import datetime
from decimal import Decimal


def number(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.8f}"


def iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value is not None else None
