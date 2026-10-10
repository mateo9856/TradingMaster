"""
Daily fiat reference rates (ECB), used to show prices in currencies other than USD.

One row per currency and ECB publication day, as *units of the currency per
1 USD*. The API converts stored USD prices with the rate for each candle's own
date (app/helpers/currencies.rate_on), and the producer converts fiat-quoted
markets (a Warsaw stock in PLN) to USD with the same rates — so a PLN stock read
back in PLN shows the price the exchange quoted.
"""

from sqlalchemy import Column, Date, String

from .candle import PRICE_TYPE
from .database import Base


class FiatRate(Base):
    __tablename__ = "fiat_rates"

    rate_date     = Column(Date, primary_key=True)
    currency      = Column(String(3), primary_key=True)
    units_per_usd = Column(PRICE_TYPE, nullable=False)   # PLN 3.91000000 → 1 USD = 3.91 PLN
