"""
Candle history endpoints.

GET  /api/v1/history/archive/runs     — recent archive-job outcomes
POST /api/v1/history/archive/{date}   — trigger the EOD archive for a date
GET  /api/v1/history/{ticker}         — query archived candles by date range
"""

import asyncio
import logging
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_active_user
from app.config import HISTORY_MAX_RANGE_DAYS, HISTORY_MAX_PAGE_SIZE
from app.helpers.intervals import validate_interval
from app.helpers.time import utc_now_naive
from app.jobs.eod_archive import ArchiveLockedError, NothingToReplaceError, run_eod_job
from app.models.database import get_db
from app.models.candle_history import CandleHistory
from app.models.job_run import EOD_ARCHIVE_JOB, JobRun
from app.models.user import User
from app.routers.market import resolve_ticker
from app.schemas import ApiResponse, ArchiveRunResponse, CandleHistoryResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/history",
    tags=["history"],
)

# Hard references to fire-and-forget archive tasks. Without this the only
# reference is the local variable, so the task can be garbage-collected
# mid-flight and any failure surfaces as nothing more than an
# "exception was never retrieved" warning.
_background_archives: set[asyncio.Task] = set()


def _resolve_interval(interval: str) -> str:
    """422 for an unsupported interval, rather than an empty result and a 404."""
    try:
        return validate_interval(interval)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        )


# ── Archive job ───────────────────────────────────────────────────────────────

@router.get("/archive/runs", response_model=ApiResponse[List[ArchiveRunResponse]])
async def list_archive_runs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Recent EOD archive runs, newest first — whether each succeeded, how much it
    wrote, and what failed.

    Public, like the other read endpoints. This is the only way the scheduled
    archive is observable: it runs in its own short-lived process, so nothing
    ever scrapes its metrics. The API exports the same rows to Prometheus.
    """
    result = await db.execute(
        select(JobRun)
        .where(JobRun.job_name == EOD_ARCHIVE_JOB)
        .order_by(JobRun.started_at.desc())
        .limit(limit)
    )
    runs = result.scalars().all()
    return ApiResponse(
        status="success",
        message=f"Found {len(runs)} archive run(s)",
        data=[ArchiveRunResponse.model_validate(r) for r in runs],
    )


@router.post(
    "/archive/{target_date}",
    response_model=ApiResponse[None],
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_archive(
    target_date: date,
    replace: bool = Query(False, description="discard the day's history and re-archive it"),
    user: User = Depends(current_active_user),
):
    """
    Trigger the EOD archive for a date, for backfilling a missed day.

    Returns immediately; the job runs in the background, so the response says
    only that it started. Re-triggering the same date is harmless — the archive
    skips rows history already holds — and a run started while another is in
    flight stops on the advisory lock instead of doubling up.

    The outcome is at GET /api/v1/history/archive/runs.
    """
    if target_date >= utc_now_naive().date():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{target_date} is not a finished day — archive a date before today.",
        )

    def _log_outcome(task: asyncio.Task) -> None:
        _background_archives.discard(task)
        if task.cancelled():
            logger.warning(f"Archive task for {target_date} was cancelled")
            return
        error = task.exception()
        if isinstance(error, ArchiveLockedError):
            # Expected when a scheduled run is already working — not a failure.
            logger.warning(f"Archive for {target_date} skipped: {error}")
        elif isinstance(error, NothingToReplaceError):
            logger.warning(f"Archive replace for {target_date} refused: {error}")
        elif error is not None:
            logger.error(f"Archive task for {target_date} failed: {error!r}")
        else:
            logger.info(f"Archive task for {target_date} finished: {task.result()}")

    task = asyncio.create_task(run_eod_job(target_date, replace=replace))
    _background_archives.add(task)
    task.add_done_callback(_log_outcome)

    logger.info(f"Manual archive triggered for {target_date} by user {user.id}")

    return ApiResponse(
        status="accepted",
        message=(
            f"Archive job started for {target_date} — "
            f"follow it at GET /api/v1/history/archive/runs"
        ),
        data=None,
    )


# ── History query ─────────────────────────────────────────────────────────────
# Registered last: the {ticker:path} converter matches slashes, so it would
# otherwise swallow /archive/runs.

@router.get("/{ticker:path}", response_model=ApiResponse[List[CandleHistoryResponse]])
async def get_history(
    ticker: str,
    date_from: date = Query(..., description="Start date (YYYY-MM-DD)"),
    date_to:   date = Query(..., description="End date (YYYY-MM-DD)"),
    exchange:  Optional[str] = None,
    interval:  str = "1m",
    limit:     int = Query(1000, ge=1, le=HISTORY_MAX_PAGE_SIZE),
    offset:    int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Query archived candle history for a ticker and date range.
    Returns up to `limit` rows ordered by timestamp ascending.
    Any spelling of a USD-equivalent market resolves to the unified ticker (BTC/USDT → BTC/USD).
    """
    ticker_upper = resolve_ticker(ticker)
    interval = _resolve_interval(interval)

    # Both bounds were previously unvalidated, so a single request could ask for
    # every row the table has ever held.
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"date_from ({date_from}) must not be after date_to ({date_to}).",
        )
    span_days = (date_to - date_from).days + 1
    if span_days > HISTORY_MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Date range of {span_days} days exceeds the maximum of "
                f"{HISTORY_MAX_RANGE_DAYS}. Request it in smaller windows."
            ),
        )

    query = (
        select(CandleHistory)
        .where(CandleHistory.ticker == ticker_upper)
        .where(CandleHistory.interval == interval)
        .where(CandleHistory.trade_date >= date_from)
        .where(CandleHistory.trade_date <= date_to)
        .order_by(CandleHistory.timestamp.asc())
        .offset(offset)
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
