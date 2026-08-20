from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import TIMESCALE_URL

SQLITE_URL = "sqlite:///./trading_master.db"

engine = create_async_engine(TIMESCALE_URL, echo=False, pool_size=10, max_overflow=20)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — yields one async DB session per request.
    Use with: db: AsyncSession = Depends(get_db)
    """
    async with AsyncSessionLocal() as session:
        yield session
 