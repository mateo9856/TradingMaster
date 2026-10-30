"""
Display currencies.

GET /api/v1/currencies — every currency prices can be shown in, with its
latest ECB rate, plus the server's default (a hint the UI uses when the
browser's time zone and language don't identify one).

Prices are stored in USD; pass `?currency=PLN` to the candle, history and
live endpoints to get them converted.
"""

import logging
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEFAULT_CURRENCY
from app.fiat.rates import latest_rates
from app.helpers.currencies import BASE_CURRENCY, FIAT_CURRENCIES, ONE
from app.models.database import get_db
from app.schemas import ApiResponse
from app.schemas.candle import Price

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/currencies", tags=["currencies"])

if DEFAULT_CURRENCY not in FIAT_CURRENCIES:
    logger.warning(f"DEFAULT_CURRENCY={DEFAULT_CURRENCY!r} is not supported — using {BASE_CURRENCY}")
SERVER_DEFAULT = DEFAULT_CURRENCY if DEFAULT_CURRENCY in FIAT_CURRENCIES else BASE_CURRENCY


class CurrencyResponse(BaseModel):
    code: str = Field(..., examples=["PLN"])
    name: str = Field(..., examples=["Polish złoty"])
    units_per_usd: Optional[Price] = Field(None, description="Latest ECB rate: 1 USD = this many units")
    rate_date: Optional[date] = None


class CurrenciesResponse(BaseModel):
    default: str = Field(..., examples=["USD"], description="Server default (DEFAULT_CURRENCY)")
    currencies: List[CurrencyResponse]


@router.get("", response_model=ApiResponse[CurrenciesResponse])
async def list_currencies(db: AsyncSession = Depends(get_db)):
    """
    Currencies with a rate are listed; one the ECB file hasn't been loaded for
    yet is left out, so the UI never offers a choice that would fail.
    """
    rates = await latest_rates(db)
    currencies = [CurrencyResponse(code=BASE_CURRENCY, name=FIAT_CURRENCIES[BASE_CURRENCY], units_per_usd=ONE)]
    for code, name in FIAT_CURRENCIES.items():
        if code in rates:
            rate_date, units_per_usd = rates[code]
            currencies.append(CurrencyResponse(code=code, name=name, units_per_usd=units_per_usd, rate_date=rate_date))

    default = SERVER_DEFAULT if any(c.code == SERVER_DEFAULT for c in currencies) else BASE_CURRENCY
    return ApiResponse(
        status="success",
        message=f"{len(currencies)} currencies",
        data=CurrenciesResponse(default=default, currencies=currencies),
    )
