import uuid
from typing import Optional

from fastapi_users import schemas
from pydantic import field_validator

from app.helpers.currencies import validate_currency


def _currency_or_none(value: Optional[str]) -> Optional[str]:
    return None if value is None else validate_currency(value)


class UserRead(schemas.BaseUser[uuid.UUID]):
    preferred_currency: Optional[str] = None


class UserCreate(schemas.BaseUserCreate):
    preferred_currency: Optional[str] = None

    @field_validator("preferred_currency")
    @classmethod
    def _currency(cls, value: Optional[str]) -> Optional[str]:
        return _currency_or_none(value)


class UserUpdate(schemas.BaseUserUpdate):
    preferred_currency: Optional[str] = None

    @field_validator("preferred_currency")
    @classmethod
    def _currency(cls, value: Optional[str]) -> Optional[str]:
        return _currency_or_none(value)
