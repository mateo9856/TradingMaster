"""
Instruments — what each market is.

GET /api/v1/instruments           — every named instrument (the catalogue), localized
GET /api/v1/instruments/{slug}    — one collected market by its page slug ("bitcoin-btc")
PUT /api/v1/instruments/{symbol}  — name or reclassify an instrument (signed-in users)

Names are proper nouns and never translated; `?lang=` translates the taxonomy
labels and the description (app/i18n).
"""

import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_active_user
from app.helpers.instruments import CRYPTO_CATEGORIES, STOCK_SECTORS, VENUES, instrument_slug
from app.helpers.markets import split_symbol
from app.i18n.instruments import localize
from app.models.database import get_db
from app.models.instrument import Instrument
from app.models.user import User
from app.routers.market import load_markets, resolve_language
from app.schemas import ApiResponse, MarketResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/instruments", tags=["instruments"])


class InstrumentResponse(BaseModel):
    symbol: str
    name: str
    short_name: str
    slug: str
    asset_class: str
    asset_class_label: Optional[str] = None
    category: Optional[str] = None
    category_label: Optional[str] = None
    venue: Optional[str] = None
    venue_label: Optional[str] = None
    country: Optional[str] = None
    ticker_symbol: Optional[str] = None
    description: str
    page_title: Optional[str] = None
    page_description: Optional[str] = None


class InstrumentUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, examples=["Bitcoin"])
    short_name: Optional[str] = Field(None, min_length=1, max_length=64, examples=["Bitcoin"])
    asset_class: Literal["crypto", "stock"] = "crypto"
    category: Optional[str] = Field(None, examples=["currency", "energy"],
                                    description="Crypto category or stock sector code")
    venue: Optional[str] = Field(None, examples=["GPW"])
    country: Optional[str] = Field(None, min_length=2, max_length=2, examples=["PL"])

    @field_validator("name", "short_name")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None

    @field_validator("country")
    @classmethod
    def _country(cls, value: Optional[str]) -> Optional[str]:
        return value.upper() if value else None

    @model_validator(mode="after")
    def _known_codes(self) -> "InstrumentUpdate":
        allowed = STOCK_SECTORS if self.asset_class == "stock" else CRYPTO_CATEGORIES
        if self.category is not None and self.category not in allowed:
            raise ValueError(f"category must be one of: {', '.join(allowed)}")
        if self.venue is not None and self.venue not in VENUES:
            raise ValueError(f"venue must be one of: {', '.join(VENUES)}")
        return self


@router.get("", response_model=ApiResponse[List[InstrumentResponse]])
async def list_instruments(
    lang: Optional[str] = Query(None, examples=["pl"]),
    db: AsyncSession = Depends(get_db),
):
    language = resolve_language(lang)
    rows = (await db.execute(select(Instrument).order_by(Instrument.asset_class, Instrument.name))).scalars().all()
    data = [InstrumentResponse(**localize(row.symbol, language, row)) for row in rows]
    return ApiResponse(status="success", message=f"Found {len(data)} instrument(s)", data=data)


@router.get("/{slug}", response_model=ApiResponse[MarketResponse])
async def get_instrument(
    slug: str,
    lang: Optional[str] = Query(None, examples=["pl"]),
    db: AsyncSession = Depends(get_db),
):
    """One collected market by the slug of its page — 404 if nothing collected has that slug."""
    language = resolve_language(lang)
    market = next((m for m in await load_markets(db, language) if m.slug == slug.lower()), None)
    if market is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No market with that name")
    return ApiResponse(status="success", message=market.name, data=market)


@router.put("/{symbol}", response_model=ApiResponse[InstrumentResponse])
async def upsert_instrument(
    symbol: str,
    body: InstrumentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Names a market added through the API, or corrects a catalogue entry. The page slug follows the name."""
    try:
        base, _ = split_symbol(f"{symbol}/USD")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))

    short_name = body.short_name or body.name
    slug = instrument_slug(short_name, base)
    clash = await db.scalar(select(Instrument.symbol).where(Instrument.slug == slug, Instrument.symbol != base))
    if clash:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{clash} already uses the page {slug!r}")

    instrument = await db.get(Instrument, base)
    if instrument is None:
        instrument = Instrument(symbol=base)
        db.add(instrument)
    instrument.name = body.name
    instrument.short_name = short_name
    instrument.slug = slug
    instrument.asset_class = body.asset_class
    instrument.category = body.category
    instrument.venue = body.venue
    instrument.country = body.country
    await db.commit()
    await db.refresh(instrument)

    logger.info(f"Instrument {base} set to {body.name!r} by user {user.id}")
    return ApiResponse(status="success", message="Instrument saved",
                       data=InstrumentResponse(**localize(base, "en", instrument)))
