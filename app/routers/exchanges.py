"""
Exchange and Symbol management endpoints.

GET  /api/v1/exchanges              — list all exchanges
POST /api/v1/exchanges              — add new exchange
PUT  /api/v1/exchanges/{id}/toggle  — enable/disable exchange

GET  /api/v1/exchanges/{id}/symbols      — list symbols for exchange
POST /api/v1/exchanges/{id}/symbols      — add symbol (one ticker + interval) to exchange
POST /api/v1/exchanges/{id}/symbols/bulk — add many tickers × intervals at once
PUT  /api/v1/symbols/{id}/toggle         — enable/disable symbol

New symbols are picked up by the producer within PRODUCER_CONFIG_REFRESH_SECONDS
and stored by the Flink job — no restart needed.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_active_user
from app.helpers.markets import unified_ticker
from app.models.database import get_db
from app.models.exchange import Exchange, Symbol
from app.models.user import User
from app.schemas import (
    ApiResponse,
    ExchangeCreate,
    ExchangeResponse,
    SymbolBulkCreate,
    SymbolBulkResult,
    SymbolCreate,
    SymbolResponse,
    SymbolSkipped,
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
async def create_exchange(
    body: ExchangeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    existing = await db.execute(select(Exchange).where(Exchange.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Exchange '{body.name}' already exists")

    exchange = Exchange(name=body.name, method=body.method)
    db.add(exchange)
    await db.commit()
    await db.refresh(exchange)
    return ApiResponse(status="success", message="Exchange created", data=ExchangeResponse.model_validate(exchange))


@router.put("/{exchange_id}/toggle", response_model=ApiResponse[ExchangeResponse])
async def toggle_exchange(
    exchange_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
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


async def _get_exchange_or_404(db: AsyncSession, exchange_id: int) -> Exchange:
    result = await db.execute(select(Exchange).where(Exchange.id == exchange_id))
    exchange = result.scalar_one_or_none()
    if not exchange:
        raise HTTPException(status_code=404, detail="Exchange not found")
    return exchange


def _safe_unified(ticker: str) -> str | None:
    try:
        return unified_ticker(ticker)
    except ValueError:
        return None   # legacy row the unified feed can't publish — can't clash either


class _SymbolIndex:
    """What an exchange already has, to reject duplicates and unified-ticker clashes."""

    def __init__(self, symbols):
        self._by_unified: dict[tuple[str, str], str] = {}
        for s in symbols:
            unified = _safe_unified(s.ticker)
            if unified:
                self._by_unified.setdefault((unified, s.interval), s.ticker)
        self._existing = {(s.ticker, s.interval) for s in symbols}

    def conflict(self, ticker: str, interval: str) -> str | None:
        """Why (ticker, interval) can't be added, or None if it can."""
        if (ticker, interval) in self._existing:
            return f"Symbol {ticker} {interval} already exists"
        unified = unified_ticker(ticker)
        other = self._by_unified.get((unified, interval))
        if other:
            return f"{other} already feeds {unified} {interval} on this exchange"
        return None

    def add(self, ticker: str, interval: str) -> None:
        self._existing.add((ticker, interval))
        self._by_unified[(unified_ticker(ticker), interval)] = ticker


async def _symbol_index(db: AsyncSession, exchange_id: int) -> _SymbolIndex:
    result = await db.execute(select(Symbol).where(Symbol.exchange_id == exchange_id))
    return _SymbolIndex(result.scalars().all())


@router.post("/{exchange_id}/symbols", response_model=ApiResponse[SymbolResponse], status_code=status.HTTP_201_CREATED)
async def create_symbol(
    exchange_id: int,
    body: SymbolCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    await _get_exchange_or_404(db, exchange_id)

    conflict = (await _symbol_index(db, exchange_id)).conflict(body.ticker, body.interval)
    if conflict:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflict)

    symbol = Symbol(exchange_id=exchange_id, ticker=body.ticker, interval=body.interval)
    db.add(symbol)
    await db.commit()
    await db.refresh(symbol)
    return ApiResponse(status="success", message="Symbol created", data=SymbolResponse.model_validate(symbol))


@router.post(
    "/{exchange_id}/symbols/bulk",
    response_model=ApiResponse[SymbolBulkResult],
    status_code=status.HTTP_201_CREATED,
)
async def create_symbols_bulk(
    exchange_id: int,
    body: SymbolBulkCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """
    Adds every ticker × interval combination in one call. Combinations that
    already exist (or clash with another market for the same unified ticker)
    are skipped and reported, not treated as errors.
    """
    await _get_exchange_or_404(db, exchange_id)
    index = await _symbol_index(db, exchange_id)

    created: list[Symbol] = []
    skipped: list[SymbolSkipped] = []
    for ticker in body.tickers:
        for interval in body.intervals:
            conflict = index.conflict(ticker, interval)
            if conflict:
                skipped.append(SymbolSkipped(ticker=ticker, interval=interval, reason=conflict))
                continue
            symbol = Symbol(exchange_id=exchange_id, ticker=ticker, interval=interval)
            db.add(symbol)
            index.add(ticker, interval)
            created.append(symbol)

    await db.commit()
    for symbol in created:
        await db.refresh(symbol)

    return ApiResponse(
        status="success",
        message=f"Created {len(created)} symbol(s), skipped {len(skipped)}",
        data=SymbolBulkResult(
            created=[SymbolResponse.model_validate(s) for s in created],
            skipped=skipped,
        ),
    )


@router.put("/symbols/{symbol_id}/toggle", response_model=ApiResponse[SymbolResponse])
async def toggle_symbol(
    symbol_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
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
