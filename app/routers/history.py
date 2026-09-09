"""
Candle history endpoints.

GET /api/v1/history/{ticker}        — query archived candles by date range
GET /api/v1/history/{ticker}/export — trigger manual EOD job for a date
"""

import logging
from datetime import date, datetime
from typing import List, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.candle_history import CandleHistory
from app.models.api_response import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/history",
    tags=["history"],
)


class CandleHistoryResponse(BaseModel):
    id:          int
    exchange:    str
    ticker:      str
    interval:    str
    trade_date:  date
    timestamp:   datetime
    open_price:  float
    high_price:  float
    low_price:   float
    close_price: float
    volume:      float
    archived_at: datetime

    class Config:
        from_attributes = True


@router.get("/{ticker:path}", response_model=ApiResponse[List[CandleHistoryResponse]])
async def get_history(
    ticker: str,
    date_from: date = Query(..., description="Start date (YYYY-MM-DD)"),
    date_to:   date = Query(..., description="End date (YYYY-MM-DD)"),
    exchange:  Optional[str] = None,
    interval:  str = "1m",
    limit:     int = 1000,
    db: AsyncSession = Depends(get_db),
):
    """
    Query archived candle history for a ticker and date range.
    Returns up to `limit` rows ordered by timestamp ascending.
    """
    ticker_upper = unquote(ticker).upper()

    query = (
        select(CandleHistory)
        .where(CandleHistory.ticker == ticker_upper)
        .where(CandleHistory.interval == interval)
        .where(CandleHistory.trade_date >= date_from)
        .where(CandleHistory.trade_date <= date_to)
        .order_by(CandleHistory.timestamp.asc())
        .limit(limit)
    )

    if exchange:
        query = query.where(CandleHistory.exchange == exchange.lower())

    result = await db.execute(query)
    rows = result.scalars().all()

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No history found for {ticker_upper} between {date_from} and {date_to}",
        )

    return ApiResponse(
        status="success",
        message=f"Found {len(rows)} candle(s) for {ticker_upper}",
        data=[CandleHistoryResponse.model_validate(r) for r in rows],
    )


@router.post("/archive/{target_date}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_archive(target_date: date):
    """
    Manually trigger the EOD archive job for a specific date.
    Useful for backfilling missed archives.
    Returns immediately — job runs in background.
    """
    import asyncio
    from app.jobs.eod_archive import run_eod_job

    logger.info(f"Manual archive triggered for {target_date}")
    asyncio.create_task(run_eod_job(target_date))

    return ApiResponse(
        status="accepted",
        message=f"Archive job started for {target_date} — check logs for progress",
        data=None,
    )