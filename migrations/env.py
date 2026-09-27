"""
Alembic environment.

Async-aware, because this project has no synchronous engine: app/models/
database.py builds a single `create_async_engine` over `postgresql+asyncpg://`.
Migrations therefore run inside `connection.run_sync(...)`.

The URL comes from ALEMBIC_DATABASE_URL if set (used by the migration test and
by any one-off run against another database), otherwise from the application's
own TIMESCALE_URL. A synchronous URL is accepted and upgraded to asyncpg, so
`psql`-style connection strings work too.
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Importing the package registers every ORM model with Base.metadata — the same
# reason app/main.py imports it. Without it autogenerate sees an empty schema.
import app.models  # noqa: F401
from app.config import TIMESCALE_URL
from app.models.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.getenv("ALEMBIC_DATABASE_URL") or TIMESCALE_URL
    # Accept a plain sync URL (psql / JDBC-style habits) and drive it with asyncpg.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it — `alembic upgrade head --sql`."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_async_engine(_database_url(), poolclass=None)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
