from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.helpers.time import utc_now_naive
from app.helpers.upsert import insert_ignore_duplicates
from app.models.monitoring import MonitoringAlert, MonitoringSettings, MonitoringTarget
from app.models.trading import Trade


async def settings_for(db: AsyncSession, user_id: UUID) -> MonitoringSettings:
    await insert_ignore_duplicates(db, MonitoringSettings, [{
        "user_id": user_id, "enabled": False, "upward_percent": 10, "downward_percent": 10,
        "check_minutes": 60, "horizon_days": 1, "revision": 0, "next_check_at": utc_now_naive(),
    }], ["user_id"])
    await db.commit()
    return await db.get(MonitoringSettings, user_id, populate_existing=True)


async def sync_holdings(db: AsyncSession, user_id: UUID) -> None:
    trades = (await db.scalars(select(Trade).where(
        Trade.user_id == user_id, Trade.closed_at.is_(None)).with_for_update())).all()
    open_ids = {trade.id for trade in trades}
    existing = (await db.scalars(select(MonitoringTarget).where(
        MonitoringTarget.user_id == user_id, MonitoringTarget.trade_id.is_not(None)))).all()
    for target in existing:
        target.active = target.trade_id in open_ids
    await insert_ignore_duplicates(db, MonitoringTarget, [{
        "user_id": user_id, "key": "trade:" + trade.id, "exchange": trade.exchange,
        "ticker": trade.ticker, "trade_id": trade.id, "reference_price": trade.buy_price,
    } for trade in trades], ["user_id", "key"])


def apply_result(db: AsyncSession, target: MonitoringTarget, settings: MonitoringSettings,
                 data: dict, now: datetime) -> None:
    result = {**data, "evaluated_at": now.isoformat(),
              "next_check_at": (now + timedelta(minutes=settings.check_minutes)).isoformat()}
    previous = target.result or {}
    snapshot = previous.get("snapshot")
    # Read legacy successful evaluations without requiring a database migration.
    if snapshot is None and previous.get("price") and previous.get("data_at"):
        snapshot = {key: previous[key] for key in ("price", "data_at", "interval") if key in previous}
    if data["status"] == "ready":
        snapshot = {key: data[key] for key in ("price", "data_at", "interval") if key in data}
        snapshot["status"] = "ready"
    if snapshot:
        result["snapshot"] = snapshot
    state = dict(target.state or {})
    if data["status"] == "ready":
        price = Decimal(data["price"])
        if target.reference_price is None:
            target.reference_price = price
        change = (price / target.reference_price - 1) * 100
        result.update(reference_price=str(target.reference_price), change_percent=str(change))
        values = {"observed": change}
        prediction = data.get("forecast", {})
        if prediction.get("status") == "ready":
            values["forecast"] = Decimal(prediction["change_percent"])
        for kind, value in values.items():
            for direction, triggered in (("up", value >= settings.upward_percent),
                                         ("down", value <= -settings.downward_percent)):
                key = f"{kind}_{direction}"
                episode = dict(state.get(key, {"active": False, "episode": 0}))
                if triggered and not episode["active"]:
                    episode["episode"] += 1
                    db.add(MonitoringAlert(user_id=target.user_id, target_id=target.id, kind=kind,
                        direction=direction, episode=episode["episode"], created_at=now,
                        payload={"exchange": target.exchange, "ticker": target.ticker,
                                 "trade_id": target.trade_id, "change_percent": str(value),
                                 "threshold_percent": str(settings.upward_percent if direction == "up" else settings.downward_percent),
                                 "data_at": data["data_at"], "forecast": prediction if kind == "forecast" else None}))
                episode["active"] = triggered
                state[key] = episode
    target.state = state
    target.result = result
