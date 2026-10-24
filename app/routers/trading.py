"""Simulated wallets, payments and executions; private reads require auth."""

import asyncio
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.auth import current_active_user
from app.models.database import get_db
from app.models.trading import Trade, Wallet
from app.models.user import User
from app.schemas.api_response import ApiResponse
from app.schemas.trading import ExecuteRequest, FundingRequest, PurchaseRequest, QuoteRequest, TopUpRequest
from app.trading import service
from app.trading.payments import accounts_data
from app.trading.quotes import QuoteUnavailable, quote_service, resolve_source, usd_rate

router = APIRouter(prefix="/api/v1/trading", tags=["simulated trading"])
Db = Annotated[AsyncSession, Depends(get_db)]
Actor = Annotated[User, Depends(current_active_user)]
RequestKey = Annotated[UUID, Header(alias="Idempotency-Key")]


def enabled() -> bool:
    return config.SIMULATED_TRADING_ENABLED or (config.APP_ENV == "development" and config.DEV_TRADING_ENABLED)


def require_trading() -> None:
    if not enabled():
        raise HTTPException(404, "Simulated trading is disabled")


def require_development() -> None:
    require_trading()
    if config.APP_ENV != "development":
        raise HTTPException(404, "Demo top-ups are development-only")


def response(data: dict) -> ApiResponse[dict]:
    return ApiResponse(status="success", data=data)


@router.get("/capabilities", response_model=ApiResponse[dict])
async def capabilities():
    return response({"enabled": enabled(), "simulated": True, "usd_per_credit": "1.00000000",
                     "payment_methods": {"credits": "enabled" if enabled() else "disabled",
                                         "card": "enabled" if enabled() else "disabled",
                                         "paypal": "enabled" if enabled() else "disabled",
                                         "bank_transfer": "coming_soon"}})


@router.post("/wallet/initialize", dependencies=[Depends(require_trading)], response_model=ApiResponse[dict])
async def initialize(db: Db, user: Actor):
    return response(await service.initialize_wallet(db, user.id))


@router.get("/wallet", dependencies=[Depends(require_trading)], response_model=ApiResponse[dict])
async def wallet(db: Db, user: Actor):
    item = await db.get(Wallet, user.id)
    if item is None:
        raise HTTPException(404, "Wallet not initialized")
    return response(service.wallet_data(item))


@router.post("/wallet/demo-top-ups", dependencies=[Depends(require_development)], response_model=ApiResponse[dict])
async def top_up(body: TopUpRequest, key: RequestKey, db: Db, user: Actor):
    return response(await service.top_up(db, user.id, str(key), body.amount))


@router.get("/payment-accounts", dependencies=[Depends(require_trading)], response_model=ApiResponse[dict])
async def payment_accounts(db: Db, user: Actor):
    await service.initialize_wallet(db, user.id)
    return response(await accounts_data(db, user.id))


@router.post("/wallet/top-ups", dependencies=[Depends(require_trading)], response_model=ApiResponse[dict])
async def fund(body: FundingRequest, key: RequestKey, db: Db, user: Actor):
    return response(await service.fund_wallet(db, user.id, str(key), body.amount,
                                            body.payment_method, body.card_type))


@router.post("/quotes", dependencies=[Depends(require_trading)], response_model=ApiResponse[dict])
async def quote(body: QuoteRequest, db: Db, user: Actor):
    return response(await service.preview(db, user.id, body))


@router.post("/trades", dependencies=[Depends(require_trading)], response_model=ApiResponse[dict])
async def buy(body: PurchaseRequest, key: RequestKey, db: Db, user: Actor):
    return response(await service.execute(db, user.id, str(key), str(body.quote_id),
                                         payment_method=body.payment_method, card_type=body.card_type))


@router.post("/trades/{trade_id}/sell", dependencies=[Depends(require_trading)], response_model=ApiResponse[dict])
async def sell(trade_id: UUID, body: ExecuteRequest, key: RequestKey, db: Db, user: Actor):
    return response(await service.execute(db, user.id, str(key), str(body.quote_id), str(trade_id)))


@router.get("/trades", dependencies=[Depends(require_trading)], response_model=ApiResponse[dict])
async def trades(db: Db, user: Actor, status: Literal["open", "closed"] = "open",
                 limit: int = Query(default=10, ge=1, le=50), offset: int = Query(default=0, ge=0)):
    filters = [Trade.user_id == user.id,
               Trade.closed_at.is_(None) if status == "open" else Trade.closed_at.is_not(None)]
    total = await db.scalar(select(func.count()).select_from(Trade).where(*filters))
    items = (await db.scalars(select(Trade).where(*filters).order_by(Trade.opened_at.desc(), Trade.id)
                             .offset(offset).limit(limit))).all()
    # Resolve SQL and FX first, then fetch all distinct books concurrently. A
    # SQLAlchemy session must not run queries concurrently across coroutines.
    sources, rates, snapshots = {}, {}, {}
    if status == "open":
        for trade in items:
            identity = (trade.exchange, trade.ticker, trade.source_ticker)
            if identity in sources or identity in snapshots:
                continue
            try:
                source = await resolve_source(db, *identity[:2], exact_source=identity[2])
                currency = source.source_ticker.split("/")[1]
                if currency not in rates:
                    try:
                        rates[currency] = await asyncio.wait_for(usd_rate(db, currency), timeout=12)
                    except Exception:
                        rates[currency] = QuoteUnavailable("USD conversion is unavailable")
                if isinstance(rates[currency], Exception):
                    raise rates[currency]
                sources[identity] = source
            except QuoteUnavailable as exc:
                snapshots[identity] = str(exc)

        async def fetch(identity, source):
            try:
                price = await quote_service.get(db, source, conversion_rate=rates[source.source_ticker.split("/")[1]])
                return identity, price[0]
            except QuoteUnavailable as exc:
                return identity, str(exc)
        snapshots.update(await asyncio.gather(*(fetch(identity, source) for identity, source in sources.items())))
    results = []
    for trade in items:
        result = {**service.trade_data(trade), "valuation": None, "valuation_error": None}
        if status == "open":
            identity = (trade.exchange, trade.ticker, trade.source_ticker)
            price = snapshots[identity]
            if isinstance(price, str):
                result["valuation_error"] = price
            else:
                result["valuation"] = service.valuation(price, trade)
        results.append(result)
    return response({"items": results, "total": total, "limit": limit, "offset": offset})
