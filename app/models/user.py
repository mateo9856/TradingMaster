from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from .database import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    """
    FastAPI Users account table — provides id/email/hashed_password plus the
    is_active/is_superuser/is_verified flags used by the auth dependencies.
    """
    __tablename__ = "users"
