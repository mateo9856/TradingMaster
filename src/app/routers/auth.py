"""Session logout endpoints that revoke shared cookie and bearer JWTs."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import cookie_backend, fastapi_users
from app.models.database import get_db
from app.models.user import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
current_user_token = fastapi_users.authenticator.current_user_token(active=True)


async def _revoke_user_sessions(db: AsyncSession, user: User) -> None:
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(auth_version=User.auth_version + 1)
    )
    await db.commit()


@router.post("/cookie/logout", status_code=204, include_in_schema=False)
async def cookie_logout(
    user_token: tuple[User, str] = Depends(current_user_token),
    db: AsyncSession = Depends(get_db),
):
    user, _token = user_token
    await _revoke_user_sessions(db, user)
    return await cookie_backend.transport.get_logout_response()


@router.post("/jwt/logout", status_code=204, include_in_schema=False)
async def jwt_logout(
    user_token: tuple[User, str] = Depends(current_user_token),
    db: AsyncSession = Depends(get_db),
):
    user, _token = user_token
    await _revoke_user_sessions(db, user)
    return Response(status_code=204)
