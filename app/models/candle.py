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
