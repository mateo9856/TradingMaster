from datetime import datetime

from pydantic import BaseModel, Field

from app.helpers.time import utc_now_naive


class CandleBase(BaseModel):
    exchange: str = Field(..., examples=["binance"])
    ticker: str = Field(..., examples=["BTC/USDT"])
    interval: str = Field("1m", examples=["1m", "5m", "1h"])
    open_price: float = Field(..., ge=0, description="Open price")
    high_price: float = Field(..., ge=0, description="Highest price")
    low_price: float = Field(..., ge=0, description="Lowest price")
    close_price: float = Field(..., ge=0, description="Closing price")
    volume: float = Field(..., ge=0, description="Trading volume")


class CandleCreate(CandleBase):
    timestamp: datetime = Field(default_factory=utc_now_naive)


class CandleResponse(CandleBase):
    id: int
    timestamp: datetime = Field(..., description="Timestamp of the candle")

    class Config:
        from_attributes = True
