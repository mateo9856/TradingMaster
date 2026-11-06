"""Durable account leases and atomic alert/evaluation commits."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import config
from app.helpers.time import utc_now_naive
from app.models.database import AsyncSessionLocal
from app.models.monitoring import MonitoringSettings, MonitoringTarget
from app.models.user import User
from app.monitoring.data import market_data
from app.monitoring.service import apply_result, sync_holdings

logger = logging.getLogger(__name__)
RUNS = Counter("monitoring_evaluations_total", "Account evaluations", ["outcome"])
DATA = Counter("monitoring_market_results_total", "Market availability", ["status"])
LAG = Histogram("monitoring_scheduling_lag_seconds", "Delay after a scheduled check")
POLL = Gauge("monitoring_last_poll_timestamp_seconds", "Last successful scheduler poll")
FORECASTS = Counter("monitoring_forecasts_total", "Forecast availability", ["status"])
ALERTS = Counter("monitoring_alerts_generated_total", "Committed alerts")
Claim = tuple[UUID, str, int]


async def claim(session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
                now: datetime | None = None) -> Claim | None:
    now = now or utc_now_naive()
    async with session_factory() as db:
        eligible = (MonitoringSettings.enabled.is_(True), MonitoringSettings.next_check_at <= now,
                    or_(MonitoringSettings.lease_until.is_(None), MonitoringSettings.lease_until <= now),
                    MonitoringSettings.user_id.in_(select(User.id).where(User.is_active.is_(True))))
        row = await db.scalar(select(MonitoringSettings).where(*eligible)
            .order_by(MonitoringSettings.next_check_at).limit(1))
        if row is None:
            return None
        token = str(uuid4())
        won = await db.scalar(update(MonitoringSettings).where(
            MonitoringSettings.user_id == row.user_id, *eligible).values(
                lease_token=token, lease_until=now + timedelta(minutes=5))
                .returning(MonitoringSettings.user_id))
        await db.commit()
        if won is None:
            return None
        LAG.observe(max(0, (now - row.next_check_at).total_seconds()))
        return row.user_id, token, row.revision


async def evaluate(claimed: Claim, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
                   now: datetime | None = None, shared_cache: dict | None = None) -> bool:
    real_clock = now is None
    now = now or utc_now_naive()
    user_id, token, revision = claimed
    async with session_factory() as db:
        settings = await db.get(MonitoringSettings, user_id)
        if settings is None or settings.lease_token != token or settings.revision != revision or not settings.enabled:
            return False
        # Take the row lock before synchronizing positions; settings writes serialize
        # with this transaction. The lease still guards a worker stalled past expiry.
        guard = await db.scalar(update(MonitoringSettings).where(
            MonitoringSettings.user_id == user_id, MonitoringSettings.lease_token == token,
            MonitoringSettings.revision == revision, MonitoringSettings.enabled.is_(True),
            MonitoringSettings.user_id.in_(select(User.id).where(User.is_active.is_(True))),
            MonitoringSettings.lease_until > now).values(lease_token=token)
            .returning(MonitoringSettings.user_id))
        if guard is None:
            return False
        await sync_holdings(db, user_id)
        targets = (await db.scalars(select(MonitoringTarget).where(
            MonitoringTarget.user_id == user_id, MonitoringTarget.active.is_(True)))).all()
        cache = shared_cache if shared_cache is not None else {}
        alert_count = 0
        for target in targets:
            key = target.exchange, target.ticker, settings.horizon_days, config.MONITORING_FORECASTS_ENABLED
            if key not in cache:
                try:
                    # No provider requests in the evaluation transaction.
                    cache[key] = await market_data(db, *key[:2], now, settings.horizon_days,
                                                   config.MONITORING_FORECASTS_ENABLED)
                except Exception:
                    logger.exception("Monitoring market failed", extra={"exchange": key[0], "ticker": key[1]})
                    # Database failures must roll back the account, not be swallowed.
                    if not db.is_active:
                        raise
                    cache[key] = {"status": "source_error"}
                DATA.labels(cache[key]["status"]).inc()
                FORECASTS.labels(cache[key].get("forecast", {}).get("status", "unavailable")).inc()
            before = len(db.new)
            apply_result(db, target, settings, cache[key], now)
            alert_count += len(db.new) - before
        # If processing exceeded the lease, discard all state and let a retry win.
        if real_clock and utc_now_naive() > settings.lease_until:
            await db.rollback()
            return False
        settings.next_check_at = now + timedelta(minutes=settings.check_minutes)
        settings.lease_token = None
        settings.lease_until = None
        await db.commit()
        ALERTS.inc(alert_count)
        RUNS.labels("success").inc()
        logger.info("Monitoring account evaluated", extra={"user_id": str(user_id), "targets": len(targets)})
        return True


async def run_once(session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
                   now: datetime | None = None, limit: int = 100) -> int:
    processed = 0
    cache = {}
    for _ in range(limit):
        claimed = await claim(session_factory, now)
        if claimed is None:
            break
        try:
            await evaluate(claimed, session_factory, now, cache)
            processed += 1
        except Exception:
            # Leave the lease to expire; a crash follows the same retry path.
            RUNS.labels("failure").inc()
            logger.exception("Monitoring evaluation failed", extra={"user_id": str(claimed[0])})
    POLL.set(utc_now_naive().replace(tzinfo=timezone.utc).timestamp())
    return processed


async def run() -> None:
    while True:
        try:
            await run_once()
        except Exception:
            logger.exception("Monitoring polling failed")
        await asyncio.sleep(60)
