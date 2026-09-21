import uuid

from fastapi_users import FastAPIUsers

from app.models.user import User
from .backend import auth_backend, cookie_backend
from .manager import get_user_manager

# Both backends are registered, so a protected endpoint accepts either the
# browser's http-only cookie or an Authorization: Bearer header.
fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [cookie_backend, auth_backend])

current_active_user = fastapi_users.current_user(active=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
