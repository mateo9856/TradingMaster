"""Exchange sessions; unsupported venues fail closed rather than guess holidays."""

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd
from exchange_calendars.exchange_calendar import ExchangeCalendar

VENUES = {"NASDAQ": "XNYS", "NYSE": "XNYS", "GPW": "XWAR", "XETRA": "XETR", "OSE": "XOSL"}


@lru_cache(maxsize=16)
def calendar(venue: str) -> ExchangeCalendar:
    name = VENUES.get(venue)
    if not name:
        raise ValueError("Unsupported stock venue")
    return xcals.get_calendar(name, start="2000-01-01", end="2040-12-31")


def sessions(start: date, end: date, venue: str | None) -> list[date]:
    if venue:
        return [stamp.date() for stamp in calendar(venue).sessions_in_range(str(start), str(end))]
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def market_open(now: datetime, venue: str) -> bool:
    return calendar(venue).is_open_on_minute(pd.Timestamp(now, tz="UTC").floor("min"))


def daily_complete(day: date, now: datetime, venue: str | None) -> bool:
    if not venue:
        return day < now.date()
    cal = calendar(venue)
    if not cal.is_session(str(day)):
        return False
    return cal.session_close(str(day)).to_pydatetime() <= now.replace(tzinfo=timezone.utc)
