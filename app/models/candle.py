from sqlalchemy import Column, Integer, Numeric, String, DateTime, UniqueConstraint
from .database import Base

# Unified-feed number format: exact decimals, 8 digits after the point
# (see app/helpers/prices.py). Shared with CandleHistory.
PRICE_TYPE = Numeric(28, 8)


class Candle(Base):
    __tablename__ = "candles"

    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String,  nullable=False, index=True)   # "binance", "kraken" etc.
    ticker = Column(String,  nullable=False, index=True)   # unified ticker, always quoted in USD: "BTC/USD"
    interval = Column(String,  nullable=False, default="1m") # "30s", "1m", "5m", "1h", "1d"
    timestamp = Column(DateTime, nullable=False)
    open_price = Column(PRICE_TYPE, nullable=False)
    high_price = Column(PRICE_TYPE, nullable=False)
    low_price = Column(PRICE_TYPE, nullable=False)
    close_price = Column(PRICE_TYPE, nullable=False)
    volume = Column(PRICE_TYPE, nullable=False)            # in base currency units (e.g. BTC)
    # The exchange's own market the candle came from ("BTC/USDT"), the currency
    # the prices above are in (always "USD"), and the native-quote → USD rate
    # the producer applied. NULL on manually inserted rows.
    source_ticker = Column(String, nullable=True)
    quote_currency = Column(String(8), nullable=True, default="USD")
    fx_rate = Column(PRICE_TYPE, nullable=True)
    # 32-hex-char W3C trace-id extracted from the producing Kafka message's
    # traceparent header by the Flink job. NULL when the header is missing
    # (e.g. rows produced before tracing was added, or OTEL_ENABLED=false).
    # Correlates a persisted row back to its Jaeger trace — see README.
    trace_id = Column(String(32), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "exchange", "ticker", "interval", "timestamp",
            name="uq_candles_exchange_ticker_interval_timestamp",
        ),
    )
