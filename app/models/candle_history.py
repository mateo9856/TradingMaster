from sqlalchemy import Column, Integer, String, DateTime, Date, Index, UniqueConstraint
from .candle import PRICE_TYPE
from .database import Base
from app.helpers.time import utc_now_naive


class CandleHistory(Base):
    """
    Cold storage for daily archived candles.

    Design decisions:
    - append-only: EOD job inserts, nobody updates
    - trade_date: the calendar date of the candle (for partitioning queries)
    - Composite index on exchange + ticker + interval + trade_date for fast
      date-range queries
    - Unique on the candle's natural key, mirroring `candles`. The archive job
      inserts ON CONFLICT DO NOTHING against it, which is what makes a re-run,
      a CronJob retry, or a manual backfill of an already-archived day a no-op
      instead of a second copy of the day.
    - No FK to exchanges/symbols — history is immutable even if exchange is deleted
    """
    __tablename__ = "candles_history"

    id          = Column(Integer, primary_key=True, index=True)
    exchange    = Column(String, nullable=False)
    ticker      = Column(String, nullable=False)
    interval    = Column(String, nullable=False, default="1m")
    trade_date  = Column(Date, nullable=False)        # date part of timestamp, for fast filtering
    timestamp   = Column(DateTime, nullable=False)
    open_price  = Column(PRICE_TYPE, nullable=False)
    high_price  = Column(PRICE_TYPE, nullable=False)
    low_price   = Column(PRICE_TYPE, nullable=False)
    close_price = Column(PRICE_TYPE, nullable=False)
    volume      = Column(PRICE_TYPE, nullable=False)
    source_ticker  = Column(String, nullable=True)       # see Candle.source_ticker
    quote_currency = Column(String(8), nullable=True, default="USD")
    fx_rate        = Column(PRICE_TYPE, nullable=True)
    archived_at = Column(DateTime, nullable=False, default=utc_now_naive)

    __table_args__ = (
        UniqueConstraint(
            "exchange", "ticker", "interval", "timestamp",
            name="uq_candles_history_exchange_ticker_interval_timestamp",
        ),
        # `interval` is in the index because every history query filters on it;
        # without it the index was only partially usable.
        Index(
            "ix_candles_history_exchange_ticker_date",
            "exchange", "ticker", "interval", "trade_date"
        ),
    )
