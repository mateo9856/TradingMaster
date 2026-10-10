from sqlalchemy import Column, String
from fastapi_users.db import SQLAlchemyBaseUserTableUUID
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
