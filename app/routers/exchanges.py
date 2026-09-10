"""
Exchange and Symbol management endpoints.

GET  /api/v1/exchanges              — list all exchanges
POST /api/v1/exchanges              — add new exchange
PUT  /api/v1/exchanges/{id}/toggle  — enable/disable exchange

GET  /api/v1/exchanges/{id}/symbols — list symbols for exchange
POST /api/v1/exchanges/{id}/symbols — add symbol to exchange
PUT  /api/v1/symbols/{id}/toggle    — enable/disable symbol
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.exchange import Exchange, Symbol
from app.schemas import (
    ApiResponse,
    ExchangeCreate,
    ExchangeResponse,
    SymbolCreate,
    SymbolResponse,
)

router = APIRouter(
    prefix="/api/v1/exchanges",
    tags=["exchanges"],
)


# ── Exchange endpoints ────────────────────────────────────────────────────────

@router.get("", response_model=ApiResponse[List[ExchangeResponse]])
async def list_exchanges(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Exchange).order_by(Exchange.name))
    exchanges = result.scalars().all()
    return ApiResponse(
        status="success",
        message=f"Found {len(exchanges)} exchange(s)",
        data=[ExchangeResponse.model_validate(e) for e in exchanges],
    )


@router.post("", response_model=ApiResponse[ExchangeResponse], status_code=status.HTTP_201_CREATED)
async def create_exchange(body: ExchangeCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Exchange).where(Exchange.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Exchange '{body.name}' already exists")

    exchange = Exchange(name=body.name, method=body.method)
    db.add(exchange)
    await db.commit()
    await db.refresh(exchange)
    return ApiResponse(status="success", message="Exchange created", data=ExchangeResponse.model_validate(exchange))


@router.put("/{exchange_id}/toggle", response_model=ApiResponse[ExchangeResponse])
async def toggle_exchange(exchange_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Exchange).where(Exchange.id == exchange_id))
    exchange = result.scalar_one_or_none()
    if not exchange:
        raise HTTPException(status_code=404, detail="Exchange not found")

    exchange.enabled = not exchange.enabled
    await db.commit()
    await db.refresh(exchange)
    return ApiResponse(
        status="success",
        message=f"Exchange {'enabled' if exchange.enabled else 'disabled'}",
        data=ExchangeResponse.model_validate(exchange),
    )


# ── Symbol endpoints ──────────────────────────────────────────────────────────

@router.get("/{exchange_id}/symbols", response_model=ApiResponse[List[SymbolResponse]])
async def list_symbols(exchange_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Symbol).where(Symbol.exchange_id == exchange_id).order_by(Symbol.ticker)
    )
    symbols = result.scalars().all()
    return ApiResponse(
        status="success",
        message=f"Found {len(symbols)} symbol(s)",
        data=[SymbolResponse.model_validate(s) for s in symbols],
    )


@router.post("/{exchange_id}/symbols", response_model=ApiResponse[SymbolResponse], status_code=status.HTTP_201_CREATED)
async def create_symbol(exchange_id: int, body: SymbolCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Exchange).where(Exchange.id == exchange_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Exchange not found")

    symbol = Symbol(exchange_id=exchange_id, ticker=body.ticker, interval=body.interval)
    db.add(symbol)
    await db.commit()
    await db.refresh(symbol)
    return ApiResponse(status="success", message="Symbol created", data=SymbolResponse.model_validate(symbol))


@router.put("/symbols/{symbol_id}/toggle", response_model=ApiResponse[SymbolResponse])
async def toggle_symbol(symbol_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Symbol).where(Symbol.id == symbol_id))
    symbol = result.scalar_one_or_none()
    if not symbol:
        raise HTTPException(status_code=404, detail="Symbol not found")

    symbol.enabled = not symbol.enabled
    await db.commit()
    await db.refresh(symbol)
    return ApiResponse(
        status="success",
        message=f"Symbol {'enabled' if symbol.enabled else 'disabled'}",
        data=SymbolResponse.model_validate(symbol),
    )
