"""Bounded, deduplicated reads of completed USD candles."""

from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.helpers.intervals import interval_to_ms
from app.models.candle import Candle
from app.models.candle_history import CandleHistory
from app.models.exchange import Exchange, Symbol
from app.models.instrument import Instrument
from app.models.monitoring import MonitoringHistoryEvent
from app.monitoring.calendar import calendar, daily_complete, market_open, sessions
from app.monitoring.forecast import forecast
from app.trading.quotes import QuoteUnavailable, resolve_source


async def price_data(db: AsyncSession, exchange: str, ticker: str, now: datetime,
                     preview: bool = False) -> dict:
    try:
        source = await resolve_source(db, exchange, ticker)
    except QuoteUnavailable:
        return {"status": "market_unavailable"}
    venue = None
    closed = False
    if source.asset_class == "stock":
        instrument = await db.get(Instrument, ticker.split("/")[0])
        venue = instrument.venue if instrument else None
        if not venue:
            return {"status": "calendar_unavailable"}
        try:
            closed = not market_open(now, venue)
            if closed and not preview:
                return {"status": "market_closed"}
        except ValueError:
            return {"status": "calendar_unavailable"}
    latest = None
    fresh = False
    configured = set((await db.scalars(select(Symbol.interval).join(Exchange).where(
        Exchange.name == exchange, Symbol.ticker == source.source_ticker, Symbol.enabled.is_(True)))).all())
    preferred = next((i for i in ("1m", "30s", "5m", "1h", "1d") if i in configured), None)
    # A stalled minute feed must not silently become an apparently fresh daily feed.
    for interval in ([preferred] if preferred else []):
        length = timedelta(milliseconds=interval_to_ms(interval))
        by_time = {}
        for model in ((CandleHistory, Candle) if preview else (Candle,)):
            query = select(model).where(
                model.exchange == exchange, model.ticker == ticker,
                model.interval == interval, model.timestamp <= now)
            if not preview:
                query = query.where(model.timestamp >= now - (
                    timedelta(days=21) if venue else max(length * 3, timedelta(minutes=30))))
            rows = (await db.scalars(query.order_by(model.timestamp.desc()).limit(3))).all()
            by_time.update({row.timestamp: row for row in rows})
        candidates = sorted(by_time.values(), key=lambda row: row.timestamp, reverse=True)
        for row in candidates:
            complete = (daily_complete(row.timestamp.date(), now, venue) if interval == "1d"
                        else row.timestamp + length <= now)
            if not complete:
                continue
            if interval == "1d":
                expected = [day for day in sessions(now.date() - timedelta(days=21), now.date(), venue)
                            if daily_complete(day, now, venue)]
                fresh = bool(expected) and row.timestamp.date() == expected[-1]
            elif venue:
                # Count open-market time, so nights, holidays and weekends do
                # not make the previous session's last bar stale at the open.
                minutes = calendar(venue).minutes_in_range(
                    pd.Timestamp(row.timestamp + length, tz="UTC").ceil("min"),
                    pd.Timestamp(now, tz="UTC").floor("min"))
                fresh = len(minutes) <= max(length.total_seconds() * 2 / 60, 20)
            else:
                fresh = now - (row.timestamp + length) <= max(length * 2, timedelta(minutes=5))
            if fresh or preview:
                latest = row
                break
        if latest:
            break
    if latest is None:
        return {"status": "stale_data"}
    if latest.close_price <= 0:
        return {"status": "invalid_history"}
    snapshot = {"price": str(latest.close_price), "data_at": latest.timestamp.isoformat(),
                "interval": latest.interval, "status": "ready" if fresh else "stale_data"}
    status = "market_closed" if closed else ("ready" if fresh else "stale_data")
    return {"status": status, "price": snapshot["price"], "data_at": snapshot["data_at"],
            "interval": latest.interval, "snapshot": snapshot}


async def market_data(db: AsyncSession, exchange: str, ticker: str, now: datetime,
                      horizon: int, forecasts_enabled: bool) -> dict:
    result = await price_data(db, exchange, ticker, now)
    if result["status"] != "ready":
        return result
    source = await resolve_source(db, exchange, ticker)
    instrument = await db.get(Instrument, ticker.split("/")[0]) if source.asset_class == "stock" else None
    venue = instrument.venue if instrument else None
    result["forecast"] = {"status": "disabled"}
    if forecasts_enabled:
        # Hot rows override archive overlap. Five years bound query and model work.
        daily = {}
        split_at = await db.scalar(select(func.max(MonitoringHistoryEvent.timestamp)).where(
            MonitoringHistoryEvent.exchange == exchange, MonitoringHistoryEvent.ticker == ticker))
        for model in (CandleHistory, Candle):
            rows = (await db.scalars(select(model).where(
                model.exchange == exchange, model.ticker == ticker, model.interval == "1d",
                model.timestamp >= max(now - timedelta(days=5 * 366), split_at or datetime.min), model.timestamp < now,
            ).order_by(model.timestamp))).all()
            for row in rows:
                if daily_complete(row.timestamp.date(), now, venue):
                    daily[row.timestamp.date()] = float(row.close_price)
        completed_days = [day for day in sessions(now.date() - timedelta(days=10), now.date(), venue)
                          if daily_complete(day, now, venue)]
        if not daily or not completed_days or max(daily) != completed_days[-1]:
            result["forecast"] = {"status": "stale_data"}
        else:
            result["forecast"] = forecast(sorted(daily.items()), horizon, venue)
    return result
