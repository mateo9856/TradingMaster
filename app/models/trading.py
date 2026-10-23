"""Development paper trading. All balances and executions settle in USD credits."""

import uuid

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON,
    Numeric, String, UniqueConstraint, Uuid,
)

from .database import Base
from app.helpers.time import utc_now_naive

AMOUNT = Numeric(28, 8)


def new_id() -> str:
    return str(uuid.uuid4())


class Wallet(Base):
    __tablename__ = "trading_wallets"
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    balance = Column(AMOUNT, nullable=False)
    version = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)
    __table_args__ = (CheckConstraint("balance >= 0", name="balance_nonnegative"),)


class TradingQuote(Base):
    __tablename__ = "trading_quotes"
    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    side = Column(String(4), nullable=False)
    exchange = Column(String(64), nullable=False)
    ticker = Column(String(40), nullable=False)
    source_ticker = Column(String(40), nullable=False)
    trade_id = Column(String(36), nullable=True)
    bid = Column(AMOUNT, nullable=False)
    ask = Column(AMOUNT, nullable=False)
    fx_rate = Column(AMOUNT, nullable=False)
    quantity = Column(AMOUNT, nullable=False)
    amount = Column(AMOUNT, nullable=False)
    source_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    delayed = Column(Boolean, nullable=False)
    consumed_at = Column(DateTime, nullable=True)


class Trade(Base):
    __tablename__ = "trading_trades"
    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(64), nullable=False)
    ticker = Column(String(40), nullable=False)
    source_ticker = Column(String(40), nullable=False)
    quantity = Column(AMOUNT, nullable=False)
    buy_price = Column(AMOUNT, nullable=False)
    cost = Column(AMOUNT, nullable=False)
    buy_quote_id = Column(String(36), ForeignKey("trading_quotes.id"), nullable=False, unique=True)
    sell_quote_id = Column(String(36), ForeignKey("trading_quotes.id"), nullable=True, unique=True)
    sell_price = Column(AMOUNT, nullable=True)
    proceeds = Column(AMOUNT, nullable=True)
    opened_at = Column(DateTime, nullable=False, default=utc_now_naive)
    closed_at = Column(DateTime, nullable=True)
    __table_args__ = (
        CheckConstraint("quantity > 0 AND cost > 0", name="positive_purchase"),
    )


class CreditEntry(Base):
    __tablename__ = "trading_credit_entries"
    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(Uuid, ForeignKey("trading_wallets.user_id", ondelete="CASCADE"), nullable=False)
    action = Column(String(16), nullable=False)
    amount = Column(AMOUNT, nullable=False)
    balance_after = Column(AMOUNT, nullable=False)
    request_key = Column(String(128), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    result = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)
    __table_args__ = (UniqueConstraint("user_id", "request_key", name="uq_credit_user_request"),)
