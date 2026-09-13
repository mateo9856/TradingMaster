from sqlalchemy import Column, Integer, Float, String, DateTime, Index, UniqueConstraint
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
    # 32-hex-char W3C trace-id extracted from the producing Kafka message's
    # traceparent header by the Flink job. NULL when the header is missing
    # (e.g. rows produced before tracing was added, or OTEL_ENABLED=false).
    # Correlates a persisted row back to its Jaeger trace — see README.
    trace_id = Column(String(32), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "exchange", "ticker", "timestamp", name="uq_candles_exchange_ticker_timestamp"
        ),
    )
