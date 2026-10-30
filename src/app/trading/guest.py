"""Opt-in development Guest provisioning through the normal user manager."""

import logging

from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.auth.manager import UserManager
from app.auth.schemas import UserCreate
from app.models.user import User

logger = logging.getLogger(__name__)


async def seed_guest(db: AsyncSession) -> None:
    if not config.DEV_GUEST_ENABLED or config.APP_ENV != "development":
        return
    manager = UserManager(SQLAlchemyUserDatabase(db, User))
    # Validate even on subsequent starts; never replace an existing password.
    data = UserCreate(email=config.DEV_GUEST_EMAIL.lower(), password=config.DEV_GUEST_PASSWORD)
    await manager.validate_password(data.password, data)
    existing = await db.scalar(select(User).where(func.lower(User.email) == data.email.lower()))
    if existing is not None:
        if not existing.is_dev_guest:
            raise RuntimeError("Configured Guest email belongs to an existing account; choose another email")
        return
    # The marker must be committed in the same transaction as the user. The
    # database adapter used by manager.create commits internally, so provision
    # with its password helper after applying the same validation above.
    hashed = manager.password_helper.hash(data.password)
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    await db.execute(insert(User).values(email=data.email, hashed_password=hashed, is_active=True,
                                         is_verified=False, is_superuser=False, is_dev_guest=True)
                     .on_conflict_do_nothing(index_elements=[User.email]))
    created = await db.scalar(select(User).where(User.email == data.email))
    if not created.is_dev_guest:
        raise RuntimeError("Configured Guest email belongs to an existing account; choose another email")
    await db.commit()
    logger.info("Development Guest account provisioned")
