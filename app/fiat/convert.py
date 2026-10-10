"""
Converting stored USD candles to the reader's currency, for the API.

REST responses load the rates for the dates they cover in one query; the
WebSocket uses the in-process cache (app/fiat/rates.fiat_rates). Either way a
candle is converted with the ECB rate for its own date, and the response says
which rate and date were used (`currency_rate`, `rate_date`).
"""

from datetime import datetime, timezone
from typing import Optional, Sequence, TypeVar

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.fiat.rates import FiatRateCache, load_series
from app.helpers.currencies import BASE_CURRENCY, PRICE_FIELDS, convert_payload, rate_on, usd_to, validate_currency

M = TypeVar("M", bound=BaseModel)


class RateUnavailableError(LookupError):
    """No ECB rate is stored yet for the currency and date asked for."""


def resolve_currency(currency: Optional[str]) -> str:
    """The upper-cased currency, USD when not given, or a 422 for an unsupported one."""
    if currency is None or not currency.strip():
        return BASE_CURRENCY
    try:
        return validate_currency(currency)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))


def _rate_unavailable(currency: str) -> HTTPException:
    # 503, not 404: the market exists, the conversion rate just hasn't been
    # downloaded yet (first start, or the ECB unreachable since).
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"No {currency} exchange rate is available yet — try again shortly, or ask for USD.",
    )


async def convert_candles(db: AsyncSession, candles: Sequence[M], currency: str) -> list[M]:
    """
    Copies of `candles` (CandleResponse / CandleHistoryResponse) with prices in
    `currency`. USD returns them untouched. 503 when a candle predates every
    stored rate for the currency.
    """
    if currency == BASE_CURRENCY or not candles:
        return list(candles)

    days = [c.timestamp.date() for c in candles]
    series = await load_series(db, currency, min(days), max(days))

    converted = []
    for candle, day in zip(candles, days):
        entry = rate_on(series, day)
        if entry is None:
            raise _rate_unavailable(currency)
        rate_date, units_per_usd = entry
        update = {field: usd_to(getattr(candle, field), units_per_usd) for field in PRICE_FIELDS}
        update.update(quote_currency=currency, currency_rate=units_per_usd, rate_date=rate_date)
        converted.append(candle.model_copy(update=update))
    return converted


def convert_live(payload: dict, currency: str, cache: FiatRateCache) -> dict:
    """
    A live (WebSocket) candle in `currency`, with the cached rate for its date.
    USD returns the shared payload itself. Raises RateUnavailableError.
    """
    if currency == BASE_CURRENCY:
        return payload
    try:
        day = datetime.fromisoformat(payload["timestamp"]).date()
    except (KeyError, TypeError, ValueError):
        day = datetime.now(timezone.utc).date()
    entry = cache.lookup(currency, day)
    if entry is None:
        raise RateUnavailableError(currency)
    return convert_payload(payload, currency, *entry)
