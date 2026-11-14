"""PostgreSQL advisory lock that keeps exchange collection singleton-wide."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

PRODUCER_LOCK_KEY = 8_531_907_443


@asynccontextmanager
async def producer_advisory_lock(engine: AsyncEngine) -> AsyncIterator[bool]:
    """Hold a session-level PostgreSQL lock for the full producer lifetime."""
    if engine.dialect.name != "postgresql":
        # Single-process local SQLite setups have no cross-process producer.
        yield True
        return

    connection = await engine.connect()
    acquired = False
    try:
        acquired = bool(await connection.scalar(select(func.pg_try_advisory_lock(PRODUCER_LOCK_KEY))))
        yield acquired
    finally:
        if acquired:
            await connection.scalar(select(func.pg_advisory_unlock(PRODUCER_LOCK_KEY)))
        await connection.close()
