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
