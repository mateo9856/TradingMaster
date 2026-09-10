from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Index
from .database import Base
from app.helpers.time import utc_now_naive


class CandleHistory(Base):
    """
    Cold storage for daily archived candles.

    Design decisions:
    - append-only: EOD job inserts, nobody updates
    - trade_date: the calendar date of the candle (for partitioning queries)
    - Composite index on exchange + ticker + trade_date for fast date-range queries
    - No FK to exchanges/symbols — history is immutable even if exchange is deleted
    """
    __tablename__ = "candles_history"

    id          = Column(Integer, primary_key=True, index=True)
    exchange    = Column(String, nullable=False)
    ticker      = Column(String, nullable=False)
    interval    = Column(String, nullable=False, default="1m")
    trade_date  = Column(Date, nullable=False)        # date part of timestamp, for fast filtering
    timestamp   = Column(DateTime, nullable=False)
    open_price  = Column(Float, nullable=False)
    high_price  = Column(Float, nullable=False)
    low_price   = Column(Float, nullable=False)
    close_price = Column(Float, nullable=False)
    volume      = Column(Float, nullable=False)
    archived_at = Column(DateTime, nullable=False, default=utc_now_naive)

    __table_args__ = (
        Index(
            "ix_candles_history_exchange_ticker_date",
            "exchange", "ticker", "trade_date"
        ),
    )
