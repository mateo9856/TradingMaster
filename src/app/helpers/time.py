"""Time helpers used across the application.

The current PostgreSQL schema uses ``TIMESTAMP WITHOUT TIME ZONE`` for
timestamps. Values stored in those columns are therefore naive datetimes,
but they are always interpreted as UTC by the application.
"""

from datetime import datetime, timezone


def utc_now_naive() -> datetime:
    """Return the current UTC time without tzinfo for database timestamps."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
