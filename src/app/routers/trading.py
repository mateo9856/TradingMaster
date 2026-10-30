"""Simulated wallets, payments and executions; private reads require auth."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.auth import current_active_user
from app.models.database import get_db
from app.models.user import User
from app.schemas.api_response import ApiResponse
from app.schemas.trading import (
    CapabilitiesResponse,
    ExecuteRequest,
    ExecutionResponse,
    FundingRequest,
    PaymentAccountsResponse,
    PurchaseRequest,
    QuoteRequest,
    QuoteResponse,
    TopUpRequest,
    TradePageResponse,
    WalletResponse,
)
from app.trading import service

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


def response[T](data: T) -> ApiResponse[T]:
    return ApiResponse(status="success", data=data)


@router.get("/capabilities", response_model=ApiResponse[CapabilitiesResponse])
async def capabilities():
    return response({"enabled": enabled(), "simulated": True, "usd_per_credit": "1.00000000",
                     "payment_methods": {"credits": "enabled" if enabled() else "disabled",
                                         "card": "enabled" if enabled() else "disabled",
                                         "paypal": "enabled" if enabled() else "disabled",
                                         "bank_transfer": "coming_soon"}})


@router.post("/wallet/initialize", dependencies=[Depends(require_trading)], response_model=ApiResponse[WalletResponse])
async def initialize(db: Db, user: Actor):
    return response(await service.initialize_wallet(db, user.id))


@router.get("/wallet", dependencies=[Depends(require_trading)], response_model=ApiResponse[WalletResponse])
async def wallet(db: Db, user: Actor):
    return response(await service.read_wallet(db, user.id))


@router.post("/wallet/demo-top-ups", dependencies=[Depends(require_development)], response_model=ApiResponse[WalletResponse])
async def top_up(body: TopUpRequest, key: RequestKey, db: Db, user: Actor):
    return response(await service.top_up(db, user.id, str(key), body.amount))


@router.get("/payment-accounts", dependencies=[Depends(require_trading)], response_model=ApiResponse[PaymentAccountsResponse])
async def payment_accounts(db: Db, user: Actor):
    return response(await service.payment_accounts(db, user.id))


@router.post("/wallet/top-ups", dependencies=[Depends(require_trading)], response_model=ApiResponse[WalletResponse])
async def fund(body: FundingRequest, key: RequestKey, db: Db, user: Actor):
    return response(await service.fund_wallet(db, user.id, str(key), body.amount,
                                            body.payment_method, body.card_type))


@router.post("/quotes", dependencies=[Depends(require_trading)], response_model=ApiResponse[QuoteResponse])
async def quote(body: QuoteRequest, db: Db, user: Actor):
    return response(await service.preview(db, user.id, body))


@router.post("/trades", dependencies=[Depends(require_trading)], response_model=ApiResponse[ExecutionResponse])
async def buy(body: PurchaseRequest, key: RequestKey, db: Db, user: Actor):
    return response(await service.execute(db, user.id, str(key), str(body.quote_id),
                                         payment_method=body.payment_method, card_type=body.card_type))


@router.post("/trades/{trade_id}/sell", dependencies=[Depends(require_trading)], response_model=ApiResponse[ExecutionResponse])
async def sell(trade_id: UUID, body: ExecuteRequest, key: RequestKey, db: Db, user: Actor):
    return response(await service.execute(db, user.id, str(key), str(body.quote_id), str(trade_id)))


@router.get("/trades", dependencies=[Depends(require_trading)], response_model=ApiResponse[TradePageResponse])
async def trades(db: Db, user: Actor, status: Literal["open", "closed"] = "open",
                 limit: int = Query(default=10, ge=1, le=50), offset: int = Query(default=0, ge=0)):
    return response(await service.list_trades(db, user.id, status, limit, offset))
