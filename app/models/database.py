from typing import AsyncGenerator
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import TIMESCALE_URL

engine = create_async_engine(TIMESCALE_URL, echo=False, pool_size=10, max_overflow=20)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Deterministic names for constraints the models don't name themselves, so
# Alembic autogenerate can reference them. The patterns deliberately reproduce
# PostgreSQL's own defaults ("exchanges_name_key", "symbols_exchange_id_fkey",
# "candles_pkey") — databases built by the pre-Alembic Base.metadata.create_all
# already carry those names, so adding this convention renames nothing.
NAMING_CONVENTION = {
    "ix":   "ix_%(column_0_label)s",
    "uq":   "%(table_name)s_%(column_0_name)s_key",
    "ck":   "%(table_name)s_%(constraint_name)s_check",
    "fk":   "%(table_name)s_%(column_0_name)s_fkey",
    "pk":   "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — yields one async DB session per request.
    Use with: db: AsyncSession = Depends(get_db)
    """
    async with AsyncSessionLocal() as session:
        yield session
