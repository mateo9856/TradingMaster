"""
What a market is: its name and classification (see app/helpers/instruments.py).

Keyed by the unified base symbol ("BTC", "PKN.WA") — the same key every
exchange's market for that coin or share maps to — so one row names the
market on every exchange that collects it.
"""

from sqlalchemy import Column, DateTime, String

from .database import Base
from app.helpers.time import utc_now_naive


class Instrument(Base):
    __tablename__ = "instruments"

    symbol      = Column(String(32), primary_key=True)          # "BTC", "PKN.WA"
    name        = Column(String(128), nullable=False)           # "Bitcoin", "ORLEN S.A."
    short_name  = Column(String(64), nullable=False)            # "Bitcoin", "Orlen"
    slug        = Column(String(128), nullable=False, unique=True)   # "bitcoin-btc", the market page URL
    asset_class = Column(String(16), nullable=False)            # "crypto" | "stock"
    category    = Column(String(32), nullable=True)             # crypto category or stock sector code
    venue       = Column(String(16), nullable=True)             # "NASDAQ", "GPW", … (stocks)
    country     = Column(String(2), nullable=True)              # ISO 3166 (stocks)
    created_at  = Column(DateTime, nullable=False, default=utc_now_naive)
