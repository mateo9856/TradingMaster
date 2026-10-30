"""Candle interval helpers.

The platform produces a fixed set of candle lengths. Keeping the list and the
millisecond conversion in one place means the API validation, the seeder and
the trade-based candle builder in the producer all agree on what "5m" means.
"""

SUPPORTED_INTERVALS: tuple[str, ...] = ("30s", "1m", "5m", "1h", "1d")

_INTERVAL_MS: dict[str, int] = {
    "30s": 30_000,
    "1m":  60_000,
    "5m":  5 * 60_000,
    "1h":  60 * 60_000,
    "1d":  24 * 60 * 60_000,
}


def validate_interval(interval: str) -> str:
    """Return the interval unchanged, or raise ValueError if it isn't supported."""
    if interval not in _INTERVAL_MS:
        raise ValueError(
            f"Unsupported interval '{interval}' — supported: {', '.join(SUPPORTED_INTERVALS)}"
        )
    return interval


def interval_to_ms(interval: str) -> int:
    """Length of one candle of `interval`, in milliseconds."""
    return _INTERVAL_MS[validate_interval(interval)]


def bucket_start(ts_ms: int, interval: str) -> int:
    """Start (ms since epoch, UTC) of the `interval` candle containing `ts_ms`."""
    size = interval_to_ms(interval)
    return (ts_ms // size) * size
