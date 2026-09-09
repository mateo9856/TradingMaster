"""
Shared fixtures for the entire test suite.

Root cause of the 404:
  aiosqlite in-memory creates a NEW database per connection.
  Even sharing the same engine, two sessions = two connections = two databases.
  The seed fixture writes to connection A, FastAPI reads from connection B → empty.

Fix:
  Force the entire test to use ONE shared connection.
  Both the seed session and FastAPI's get_db override use the same connection,
  so they literally see the same in-memory SQLite database.
"""

import pytest_asyncio
from datetime import datetime
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from unittest.mock import AsyncMock, patch

from app.models.database import Base, get_db
from app.models.candle import Candle as CandleORM
from app.models.candle_history import CandleHistory
from app.models.exchange import Exchange, Symbol

# Use a file-backed SQLite database so committed seed rows remain visible
# across pytest-asyncio event loops and FastAPI request sessions.
TEST_DB_URL = "sqlite+aiosqlite:///./test_trading_master.db"

test_engine = create_async_engine(
    TEST_DB_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 5,
    },
    echo=False,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── DB lifecycle ──────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def reset_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


# ── Shared session ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_session(reset_database) -> AsyncSession:
    async with TestingSessionLocal() as session:
        yield session


# ── FastAPI client ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(reset_database) -> AsyncClient:
    async def override_get_db():
        async with TestingSessionLocal() as session:
            yield session

    with patch("app.main.run_producer", new_callable=AsyncMock) as mock_producer:
        mock_producer.return_value = None

        from app.main import app
        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac

        app.dependency_overrides.clear()


# ── Seed fixtures ─────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def btc_candle(db_session: AsyncSession) -> CandleORM:
    candle = CandleORM(
        exchange="binance",
        ticker="BTC/USDT",
        interval="1m",
        timestamp=datetime(2026, 6, 23, 12, 0, 0),
        open_price=65000.0,
        high_price=65300.0,
        low_price=64850.0,
        close_price=65200.0,
        volume=15.4,
    )
    db_session.add(candle)
    await db_session.commit()
    await db_session.refresh(candle)
    return candle


@pytest_asyncio.fixture
async def multi_candles(db_session: AsyncSession) -> list[CandleORM]:
    candles = [
        CandleORM(
            exchange="binance", ticker="BTC/USDT", interval="1m",
            timestamp=datetime(2026, 6, 23, 12, 0, 0),
            open_price=65000.0, high_price=65300.0, low_price=64850.0,
            close_price=65200.0, volume=15.4,
        ),
        CandleORM(
            exchange="kraken", ticker="BTC/USDT", interval="1m",
            timestamp=datetime(2026, 6, 23, 12, 1, 0),
            open_price=65100.0, high_price=65400.0, low_price=64900.0,
            close_price=65300.0, volume=10.2,
        ),
        CandleORM(
            exchange="binance", ticker="ETH/USDT", interval="1m",
            timestamp=datetime(2026, 6, 23, 12, 0, 0),
            open_price=3500.0, high_price=3550.0, low_price=3490.0,
            close_price=3525.0, volume=88.5,
        ),
        CandleORM(
            exchange="binance", ticker="BTC/USDT", interval="5m",
            timestamp=datetime(2026, 6, 23, 12, 5, 0),
            open_price=65200.0, high_price=65500.0, low_price=65100.0,
            close_price=65400.0, volume=42.1,
        ),
    ]
    db_session.add_all(candles)
    await db_session.commit()
    return candles


@pytest_asyncio.fixture
async def exchange(db_session: AsyncSession) -> Exchange:
    exchange = Exchange(name="binance", method="multi")
    db_session.add(exchange)
    await db_session.commit()
    await db_session.refresh(exchange)
    return exchange


@pytest_asyncio.fixture
async def history_candles(db_session: AsyncSession) -> list[CandleHistory]:
    candles = [
        CandleHistory(
            exchange="binance", ticker="BTC/USDT", interval="1m",
            trade_date=datetime(2026, 6, 22).date(),
            timestamp=datetime(2026, 6, 22, 12, 0),
            open_price=65000.0, high_price=65300.0, low_price=64850.0,
            close_price=65200.0, volume=15.4,
        ),
        CandleHistory(
            exchange="kraken", ticker="BTC/USDT", interval="1m",
            trade_date=datetime(2026, 6, 23).date(),
            timestamp=datetime(2026, 6, 23, 12, 0),
            open_price=65100.0, high_price=65400.0, low_price=64900.0,
            close_price=65300.0, volume=10.2,
        ),
        CandleHistory(
            exchange="binance", ticker="ETH/USDT", interval="1m",
            trade_date=datetime(2026, 6, 22).date(),
            timestamp=datetime(2026, 6, 22, 12, 0),
            open_price=3500.0, high_price=3550.0, low_price=3490.0,
            close_price=3525.0, volume=88.5,
        ),
    ]
    db_session.add_all(candles)
    await db_session.commit()
    return candles
