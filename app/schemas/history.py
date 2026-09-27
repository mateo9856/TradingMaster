from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.candle import Price


class CandleHistoryResponse(BaseModel):
    id: int
    exchange: str
    ticker: str
    interval: str
    trade_date: date
    timestamp: datetime
    open_price: Price
    high_price: Price
    low_price: Price
    close_price: Price
    volume: Price
    source_ticker: Optional[str] = None
    quote_currency: Optional[str] = None
    fx_rate: Optional[Price] = None
    archived_at: datetime

    class Config:
        from_attributes = True


class ArchiveRunResponse(BaseModel):
    """
    One EOD archive run — see GET /api/v1/history/archive/runs.

    `rows_skipped` counts candles history already held: on a re-run or a
    CronJob retry it is the whole day and `rows_archived` is zero, which is the
    job doing exactly the right thing rather than a problem.
    """

    id: int
    job_name: str
    target_date: Optional[date] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str                       # running | success | failure
    rows_archived: int
    rows_skipped: int
    rows_deleted: int
    files_written: int
    error: Optional[str] = None

    class Config:
        from_attributes = True
