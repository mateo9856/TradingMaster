from datetime import date, datetime

from pydantic import BaseModel


class CandleHistoryResponse(BaseModel):
    id: int
    exchange: str
    ticker: str
    interval: str
    trade_date: date
    timestamp: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    archived_at: datetime

    class Config:
        from_attributes = True
