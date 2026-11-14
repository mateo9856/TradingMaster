"""Concurrency and transaction invariants on PostgreSQL, the production dialect."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.helpers.time import utc_now_naive
from app.kafka.producer_lock import producer_advisory_lock
from app.models import Base
from app.models.exchange import Exchange, Symbol
from app.models.monitoring import MonitoringSettings
from app.models.producer_status import ProducerStatus
from app.models.trading import (
    CreditEntry,
    Payment,
    PaymentAccount,
    TradingQuote,
    Wallet,
)
from app.models.user import User
from app.monitoring.service import settings_for
from app.monitoring.worker import claim
from app.producer_runner import record_active_instance, record_duplicate_start
from app.trading.service import execute, fund_wallet

TEST_POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not TEST_POSTGRES_URL,
    reason="set TEST_POSTGRES_URL to a disposable PostgreSQL to run business concurrency tests",
)


def _database_url(url: str, database: str, *, async_driver: bool = False) -> str:
    parts = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    scheme = "postgresql+asyncpg" if async_driver else "postgresql"
    return urlunsplit((scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


@pytest_asyncio.fixture
async def postgres_sessions():
    """Create an isolated database; never point these tests at a shared schema."""
    if not TEST_POSTGRES_URL:
        pytest.skip("TEST_POSTGRES_URL is not configured")

    import psycopg

    database = f"tm_business_{uuid.uuid4().hex[:12]}"
    admin_url = _database_url(TEST_POSTGRES_URL, "postgres")
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{database}"')

    database_url = _database_url(TEST_POSTGRES_URL, database, async_driver=True)
    engine = create_async_engine(database_url, pool_size=5, max_overflow=5)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database,),
            )
            connection.execute(f'DROP DATABASE IF EXISTS "{database}"')


async def _create_wallet(session_factory, balance: Decimal = Decimal("1000")) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with session_factory() as db:
        db.add_all([
            User(id=user_id, email=f"{user_id}@example.com", hashed_password="unused", is_active=True),
            Exchange(name="kraken", method="ohlcv", asset_class="crypto", enabled=True),
        ])
        await db.flush()
        exchange = await db.scalar(select(Exchange).where(Exchange.name == "kraken"))
        db.add_all([
            Symbol(exchange_id=exchange.id, ticker="BTC/USD", interval="1m", enabled=True),
            Wallet(user_id=user_id, balance=balance, version=0),
        ])
        await db.commit()
    return user_id


async def _add_buy_quote(session_factory, user_id: uuid.UUID, amount: Decimal = Decimal("100")) -> str:
    now = utc_now_naive()
    quote = TradingQuote(
        user_id=user_id, side="buy", exchange="kraken", ticker="BTC/USD", source_ticker="BTC/USD",
        bid=amount - 1, ask=amount, fx_rate=Decimal("1"), quantity=Decimal("1"), amount=amount,
        received_at=now, expires_at=now + timedelta(seconds=15), delayed=False,
    )
    async with session_factory() as db:
        db.add(quote)
        await db.commit()
        return quote.id


async def test_concurrent_idempotent_execution_commits_once_on_postgres(postgres_sessions):
    user_id = await _create_wallet(postgres_sessions)
    quote_id = await _add_buy_quote(postgres_sessions, user_id)

    async def run_once():
        async with postgres_sessions() as db:
            return await execute(db, user_id, "same-request", quote_id, payment_method="paypal")

    first, retry = await asyncio.gather(run_once(), run_once())

    assert first == retry
    async with postgres_sessions() as db:
        assert await db.scalar(select(Wallet.balance).where(Wallet.user_id == user_id)) == Decimal("1000")
        assert await db.scalar(select(func.count()).select_from(CreditEntry)) == 1
        assert await db.scalar(select(func.count()).select_from(Payment)) == 1


async def test_competing_postgres_purchases_cannot_overspend_wallet(postgres_sessions):
    user_id = await _create_wallet(postgres_sessions, Decimal("100"))
    quotes = [await _add_buy_quote(postgres_sessions, user_id, Decimal("70")) for _ in range(2)]

    async def run_once(index: int):
        async with postgres_sessions() as db:
            try:
                return await execute(db, user_id, f"request-{index}", quotes[index])
            except Exception as error:
                await db.rollback()
                return error

    results = await asyncio.gather(run_once(0), run_once(1))

    assert sum(isinstance(result, dict) for result in results) == 1
    async with postgres_sessions() as db:
        assert await db.scalar(select(Wallet.balance).where(Wallet.user_id == user_id)) == Decimal("30")
        assert await db.scalar(select(func.count()).select_from(CreditEntry)) == 1


async def test_postgres_payment_insert_failure_rolls_back_wallet_and_account(postgres_sessions):
    from sqlalchemy import event

    user_id = await _create_wallet(postgres_sessions)
    async with postgres_sessions() as db:
        db.add(PaymentAccount(user_id=user_id, kind="debit", balance=Decimal("1000")))
        await db.commit()

    def fail_payment_insert(*_args):
        raise RuntimeError("payment insert failed")

    event.listen(Payment, "before_insert", fail_payment_insert)
    try:
        async with postgres_sessions() as db:
            with pytest.raises(RuntimeError, match="payment insert failed"):
                await fund_wallet(db, user_id, "funding-request", Decimal("50"), "card", "debit")
            await db.rollback()
    finally:
        event.remove(Payment, "before_insert", fail_payment_insert)

    async with postgres_sessions() as db:
        assert await db.scalar(select(Wallet.balance).where(Wallet.user_id == user_id)) == Decimal("1000")
        assert await db.scalar(select(PaymentAccount.balance).where(
            PaymentAccount.user_id == user_id, PaymentAccount.kind == "debit")) == Decimal("1000")
        assert await db.scalar(select(func.count()).select_from(CreditEntry)) == 0
        assert await db.scalar(select(func.count()).select_from(Payment)) == 0


async def test_competing_postgres_monitoring_workers_claim_an_account_once(postgres_sessions):
    user_id = await _create_wallet(postgres_sessions)
    now = utc_now_naive()
    async with postgres_sessions() as db:
        db.add(MonitoringSettings(
            user_id=user_id, enabled=True, upward_percent=10, downward_percent=10,
            check_minutes=60, horizon_days=1, revision=0, next_check_at=now,
        ))
        await db.commit()

    claims = await asyncio.gather(claim(postgres_sessions, now), claim(postgres_sessions, now))

    assert sum(claimed is not None for claimed in claims) == 1


async def test_postgres_settings_upsert_is_idempotent_under_competition(postgres_sessions):
    user_id = await _create_wallet(postgres_sessions)

    async def get_or_create():
        async with postgres_sessions() as db:
            return await settings_for(db, user_id)

    settings = await asyncio.gather(get_or_create(), get_or_create())

    assert all(row.user_id == user_id for row in settings)
    async with postgres_sessions() as db:
        assert await db.scalar(select(func.count()).select_from(MonitoringSettings)) == 1


async def test_postgres_producer_lock_rejects_a_second_live_instance(postgres_sessions):
    engine = postgres_sessions.kw["bind"]

    async with producer_advisory_lock(engine) as first:
        assert first is True
        async with producer_advisory_lock(engine) as second:
            assert second is False

    async with producer_advisory_lock(engine) as after_release:
        assert after_release is True


async def test_duplicate_producer_starts_are_persisted(postgres_sessions):
    instance_id = str(uuid.uuid4())
    await record_active_instance(instance_id, postgres_sessions)
    await record_duplicate_start(postgres_sessions)
    await record_duplicate_start(postgres_sessions)

    async with postgres_sessions() as db:
        status = await db.get(ProducerStatus, 1)
        assert status.instance_id == instance_id
        assert status.heartbeat_at is not None
        assert status.duplicate_starts == 2
