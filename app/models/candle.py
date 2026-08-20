from pydantic import BaseModel, Field
from datetime import datetime
from sqlalchemy import Column, Integer, Float, String, DateTime, Index
from .database import Base

class Candle(Base):
    __tablename__ = "candles"

    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String,  nullable=False, index=True)   # "binance", "kraken" etc.
    ticker = Column(String,  nullable=False, index=True)   # "BTC/USDT"
    interval = Column(String,  nullable=False, default="1m") # "1m", "5m", "1h"
    timestamp = Column(DateTime, nullable=False)
    open_price = Column(Float,  nullable=False)
    high_price = Column(Float,  nullable=False)
    low_price = Column(Float,  nullable=False)
    close_price = Column(Float,  nullable=False)
    volume = Column(Float,  nullable=False)

    __table_args__ = (
        Index("ix_candles_exchange_ticker_timestamp", "exchange", "ticker", "timestamp"),
    )

class CandleBase(BaseModel):
    exchange:    str   = Field(..., examples=["binance"])
    ticker:      str   = Field(..., examples=["BTC/USDT"])
    interval:    str   = Field("1m", examples=["1m", "5m", "1h"])
    open_price:  float = Field(..., ge=0, description="Open price")
    high_price:  float = Field(..., ge=0, description="Highest price")
    low_price:   float = Field(..., ge=0, description="Lowest price")
    close_price: float = Field(..., ge=0, description="Closing price")
    volume:      float = Field(..., ge=0, description="Trading volume")

class CandleCreate(CandleBase):
    timestamp: datetime = Field(default_factory=datetime.now)

class CandleResponse(CandleBase):
    id: int
    timestamp: datetime = Field(..., description="Timestamp of the candle")

    class Config:
        from_attributes = True