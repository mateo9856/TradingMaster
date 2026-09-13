import uuid

from fastapi_users import FastAPIUsers

from app.models.user import User
from .backend import auth_backend
from .manager import get_user_manager

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
