"""User authentication: the same JWT via an http-only cookie (browser) or a bearer header (API clients)."""

from .users import current_active_user, current_superuser, fastapi_users
from .schemas import UserCreate, UserRead, UserUpdate
from .backend import auth_backend, cookie_backend
from .csrf import CSRF_HEADER, csrf_protect

__all__ = [
    "current_active_user",
    "current_superuser",
    "fastapi_users",
    "auth_backend",
    "cookie_backend",
    "csrf_protect",
    "CSRF_HEADER",
    "UserCreate",
    "UserRead",
    "UserUpdate",
]
