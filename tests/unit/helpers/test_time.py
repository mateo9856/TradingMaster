from datetime import datetime

from app.helpers.time import utc_now_naive
from app.models.candle_history import CandleHistory
from app.models.exchange import Exchange, Symbol


def test_utc_now_naive_returns_a_timezone_naive_utc_datetime():
    value = utc_now_naive()

    assert isinstance(value, datetime)
    assert value.tzinfo is None


def test_database_timestamp_defaults_match_timestamp_without_time_zone_columns():
    for model, column_name in (
        (Exchange, "created_at"),
        (Symbol, "created_at"),
        (CandleHistory, "archived_at"),
    ):
        column = model.__table__.c[column_name]

        assert column.type.timezone is False
        assert column.default.arg(None).tzinfo is None
