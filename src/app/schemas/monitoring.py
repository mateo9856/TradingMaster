from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    upward_percent: Decimal = Field(default=Decimal(10), gt=0, le=100, decimal_places=4)
    downward_percent: Decimal = Field(default=Decimal(10), gt=0, le=100, decimal_places=4)
    check_minutes: Literal[15, 60, 1440] = 60
    horizon_days: int = Field(default=1, ge=1, le=365, strict=True)


class WatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exchange: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    ticker: str = Field(min_length=1, max_length=40)
    enable_monitoring: bool = False


class MonitoringToggle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class SettingsRead(SettingsUpdate):
    next_check_at: datetime | None
    forecasts_enabled: bool


class TargetRead(BaseModel):
    id: UUID
    exchange: str
    ticker: str
    trade_id: UUID | None
    reference_price: Decimal | None
    created_at: datetime
    result: dict[str, Any]


class AlertRead(BaseModel):
    id: UUID
    kind: Literal["observed", "forecast"]
    direction: Literal["up", "down"]
    payload: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


class AlertPage(BaseModel):
    items: list[AlertRead]
    unread_count: int
    checked_at: datetime
