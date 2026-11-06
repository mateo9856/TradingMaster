"""Authenticated monitoring APIs; actor identity never comes from request bodies."""

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.auth import current_active_user
from app.helpers.time import utc_now_naive
from app.helpers.upsert import insert_ignore_duplicates
from app.models.database import get_db
from app.models.monitoring import MonitoringAlert, MonitoringSettings, MonitoringTarget
from app.models.trading import Trade
from app.models.user import User
from app.monitoring.data import price_data
from app.monitoring.service import settings_for
from app.routers.market import resolve_ticker
from app.schemas.api_response import ApiResponse
from app.schemas.monitoring import (
    AlertPage,
    MonitoringToggle,
    SettingsRead,
    SettingsUpdate,
    TargetRead,
    WatchCreate,
)
from app.trading.quotes import QuoteUnavailable, resolve_source

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])
Db = Annotated[AsyncSession, Depends(get_db)]
Actor = Annotated[User, Depends(current_active_user)]


def response(data: Any) -> ApiResponse:
    return ApiResponse(status="success", data=data)


def serialize_settings(row: MonitoringSettings) -> dict:
    return {**{name: getattr(row, name) for name in SettingsUpdate.model_fields},
            "next_check_at": row.next_check_at if row.enabled else None,
            "forecasts_enabled": config.MONITORING_FORECASTS_ENABLED}


def serialize_target(row: MonitoringTarget) -> dict:
    return {name: getattr(row, name) for name in (
        "id", "exchange", "ticker", "trade_id", "reference_price", "created_at", "result")}


@router.get("/settings", response_model=ApiResponse[SettingsRead])
async def get_settings(db: Db, user: Actor) -> ApiResponse:
    return response(serialize_settings(await settings_for(db, user.id)))


@router.put("/settings", response_model=ApiResponse[SettingsRead])
async def update_settings(body: SettingsUpdate, db: Db, user: Actor) -> ApiResponse:
    await settings_for(db, user.id)
    await db.execute(update(MonitoringSettings).where(MonitoringSettings.user_id == user.id).values(
        **body.model_dump(), revision=MonitoringSettings.revision + 1, next_check_at=utc_now_naive(),
        lease_token=None, lease_until=None))
    await db.commit()
    return response(serialize_settings(await db.get(MonitoringSettings, user.id, populate_existing=True)))


@router.patch("/settings", response_model=ApiResponse[SettingsRead])
async def toggle_settings(body: MonitoringToggle, db: Db, user: Actor) -> ApiResponse:
    await settings_for(db, user.id)
    await db.execute(update(MonitoringSettings).where(MonitoringSettings.user_id == user.id).values(
        enabled=body.enabled, revision=MonitoringSettings.revision + 1, next_check_at=utc_now_naive(),
        lease_token=None, lease_until=None))
    await db.commit()
    return response(serialize_settings(await db.get(MonitoringSettings, user.id, populate_existing=True)))


@router.get("/watchlist", response_model=ApiResponse[list[TargetRead]])
async def watchlist(db: Db, user: Actor) -> ApiResponse:
    rows = (await db.scalars(select(MonitoringTarget).where(
        MonitoringTarget.user_id == user.id, MonitoringTarget.trade_id.is_(None))
        .order_by(MonitoringTarget.created_at))).all()
    return response([serialize_target(row) for row in rows])


@router.post("/watchlist", response_model=ApiResponse[TargetRead])
async def add_watch(body: WatchCreate, db: Db, user: Actor) -> ApiResponse:
    ticker = resolve_ticker(body.ticker)
    try:
        await resolve_source(db, body.exchange, ticker)
    except QuoteUnavailable as exc:
        raise HTTPException(422, str(exc)) from exc
    await settings_for(db, user.id)
    # Serialize additions and settings updates for this account.
    values = {"revision": MonitoringSettings.revision + 1, "next_check_at": utc_now_naive(),
              "lease_token": None, "lease_until": None}
    if body.enable_monitoring:
        values["enabled"] = True
    await db.execute(update(MonitoringSettings).where(MonitoringSettings.user_id == user.id).values(**values))
    key = f"watch:{body.exchange}:{ticker}"
    row = await db.scalar(select(MonitoringTarget).where(MonitoringTarget.user_id == user.id, MonitoringTarget.key == key))
    if row is None:
        count = await db.scalar(select(func.count()).select_from(MonitoringTarget).where(
            MonitoringTarget.user_id == user.id, MonitoringTarget.trade_id.is_(None)))
        if count >= 100:
            raise HTTPException(422, "Watchlist limit is 100 markets")
        await insert_ignore_duplicates(db, MonitoringTarget, [{
            "user_id": user.id, "key": key, "exchange": body.exchange, "ticker": ticker,
        }], ["user_id", "key"])
        row = await db.scalar(select(MonitoringTarget).where(MonitoringTarget.user_id == user.id, MonitoringTarget.key == key))
        preview = await price_data(db, body.exchange, ticker, utc_now_naive(), preview=True)
        row.result = {"snapshot": preview["snapshot"]} if "snapshot" in preview else {"preview_status": preview["status"]}
        if preview["status"] == "ready":
            row.reference_price = preview["price"]
    await db.commit()
    return response(serialize_target(row))


@router.delete("/watchlist/{target_id}", response_model=ApiResponse[None])
async def remove_watch(target_id: UUID, db: Db, user: Actor) -> ApiResponse:
    row = await db.scalar(select(MonitoringTarget).where(
        MonitoringTarget.id == str(target_id), MonitoringTarget.user_id == user.id,
        MonitoringTarget.trade_id.is_(None)))
    if row is None:
        raise HTTPException(404, "Watch entry not found")
    await db.execute(update(MonitoringSettings).where(MonitoringSettings.user_id == user.id)
        .values(revision=MonitoringSettings.revision + 1, lease_token=None, lease_until=None))
    await db.delete(row)
    await db.commit()
    return response(None)


@router.get("/holdings", response_model=ApiResponse[list[TargetRead]])
async def holdings(db: Db, user: Actor, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)) -> ApiResponse:
    rows = (await db.execute(select(Trade, MonitoringTarget).outerjoin(MonitoringTarget, MonitoringTarget.trade_id == Trade.id)
        .where(Trade.user_id == user.id, Trade.closed_at.is_(None)).order_by(Trade.opened_at.desc())
        .limit(limit).offset(offset))).all()
    return response([serialize_target(target) if target else {
        "id": trade.id, "trade_id": trade.id, "exchange": trade.exchange, "ticker": trade.ticker,
        "reference_price": trade.buy_price, "created_at": trade.opened_at, "result": {},
    } for trade, target in rows])


@router.get("/alerts", response_model=ApiResponse[AlertPage])
async def alerts(db: Db, user: Actor, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                 after: datetime | None = None, after_id: UUID | None = None) -> ApiResponse:
    checked_at = utc_now_naive()
    query = select(MonitoringAlert).where(MonitoringAlert.user_id == user.id)
    if after_id is not None and after is None:
        raise HTTPException(422, "after_id requires after")
    if after is not None:
        if after.tzinfo is not None:
            after = after.astimezone(timezone.utc).replace(tzinfo=None)
        query = query.where(or_(MonitoringAlert.created_at > after,
            and_(MonitoringAlert.created_at == after, MonitoringAlert.id > str(after_id)))
            if after_id else MonitoringAlert.created_at >= after)
        query = query.order_by(MonitoringAlert.created_at, MonitoringAlert.id)
    else:
        query = query.order_by(MonitoringAlert.created_at.desc(), MonitoringAlert.id.desc())
    rows = (await db.scalars(query.limit(limit).offset(offset))).all()
    unread = await db.scalar(select(func.count()).select_from(MonitoringAlert).where(
        MonitoringAlert.user_id == user.id, MonitoringAlert.read_at.is_(None)))
    return response({"items": [{name: getattr(row, name) for name in (
        "id", "kind", "direction", "payload", "created_at", "read_at")} for row in rows],
        "unread_count": unread, "checked_at": checked_at})


@router.patch("/alerts/{alert_id}/read", response_model=ApiResponse[None])
async def read_alert(alert_id: UUID, db: Db, user: Actor) -> ApiResponse:
    row = await db.scalar(select(MonitoringAlert).where(
        MonitoringAlert.id == str(alert_id), MonitoringAlert.user_id == user.id))
    if row is None:
        raise HTTPException(404, "Alert not found")
    row.read_at = row.read_at or utc_now_naive()
    await db.commit()
    return response(None)
