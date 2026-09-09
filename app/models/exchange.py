from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base


class Exchange(Base):
    """
    Stores configured exchanges.
    Enabled/disabled flag lets you pause an exchange without code changes.
    """
    __tablename__ = "exchanges"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String, nullable=False, unique=True)   # "binance", "kraken"
    method     = Column(String, nullable=False)                 # "multi", "ohlcv", "trades"
    enabled    = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    symbols = relationship("Symbol", back_populates="exchange_rel", cascade="all, delete-orphan")


class Symbol(Base):
    """
    Stores symbols per exchange.
    Adding a new symbol is a DB insert — no code deploy needed.
    """
    __tablename__ = "symbols"

    id          = Column(Integer, primary_key=True, index=True)
    exchange_id = Column(Integer, ForeignKey("exchanges.id"), nullable=False)
    ticker      = Column(String, nullable=False)    # "BTC/USDT", "BTC/USD"
    interval    = Column(String, nullable=False, default="1m")
    enabled     = Column(Boolean, nullable=False, default=True)
    created_at  = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    exchange_rel = relationship("Exchange", back_populates="symbols")

    __table_args__ = (
        UniqueConstraint("exchange_id", "ticker", "interval", name="uq_symbol_exchange_ticker_interval"),
    )