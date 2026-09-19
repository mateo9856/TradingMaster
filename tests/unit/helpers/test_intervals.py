import pytest

from app.helpers.intervals import SUPPORTED_INTERVALS, bucket_start, interval_to_ms, validate_interval


@pytest.mark.parametrize("interval, expected_ms", [
    ("30s", 30_000),
    ("1m", 60_000),
    ("5m", 300_000),
    ("1h", 3_600_000),
    ("1d", 86_400_000),
])
def test_interval_to_ms_for_every_supported_interval(interval, expected_ms):
    assert interval_to_ms(interval) == expected_ms


def test_supported_intervals_are_the_business_set():
    assert SUPPORTED_INTERVALS == ("30s", "1m", "5m", "1h", "1d")


@pytest.mark.parametrize("interval", ["7m", "", "abc", "1M", "15m", None])
def test_unsupported_interval_raises(interval):
    with pytest.raises(ValueError, match="Unsupported interval"):
        interval_to_ms(interval)
    with pytest.raises(ValueError):
        validate_interval(interval)


def test_bucket_start_aligns_to_30_seconds():
    assert bucket_start(29_999, "30s") == 0
    assert bucket_start(30_000, "30s") == 30_000
    assert bucket_start(59_999, "30s") == 30_000


def test_bucket_start_aligns_to_utc_day():
    day = 86_400_000
    assert bucket_start(3 * day + 12_345, "1d") == 3 * day
    assert bucket_start(4 * day - 1, "1d") == 3 * day


def test_bucket_start_rejects_unsupported_interval():
    with pytest.raises(ValueError):
        bucket_start(0, "2m")
