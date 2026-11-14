from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy import Boolean, Column, Integer, String, false

from .database import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    """
    FastAPI Users account table — provides id/email/hashed_password plus the
    is_active/is_superuser/is_verified flags used by the auth dependencies.
    """
    __tablename__ = "users"

    # Display currency chosen in the UI ("PLN"); NULL means "detect from the
    # browser". Validated against app/helpers/currencies.FIAT_CURRENCIES.
    preferred_currency = Column(String(3), nullable=True)
    is_dev_guest = Column(Boolean, nullable=False, default=False, server_default=false())
    # Added without changing existing accounts; old JWTs carry implicit version 0.
    auth_version = Column(Integer, nullable=False, default=0, server_default="0")
