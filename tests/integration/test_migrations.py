"""
End-to-end migration tests against a real PostgreSQL.

Skipped unless TEST_POSTGRES_URL points at a database these tests may DROP and
recreate. The rest of the suite runs on SQLite with Base.metadata.create_all,
which is fast and dialect-neutral but proves nothing about the migrations —
this is the only thing standing between a model change and a broken deploy.

    docker run -d --name tm-test-pg -e POSTGRES_USER=user \
        -e POSTGRES_PASSWORD=testpw -e POSTGRES_DB=tradingmaster \
        -p 55432:5432 postgres:16
    TEST_POSTGRES_URL=postgresql://user:testpw@localhost:55432/tradingmaster \
        pytest tests/integration/test_migrations.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not TEST_POSTGRES_URL,
    reason="set TEST_POSTGRES_URL to a disposable PostgreSQL to run the migration tests",
)


def _sync_url(url: str) -> str:
    """psycopg/asyncpg-agnostic sync URL for the admin connection."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(_sync_url(url))
    return urlunsplit(parts._replace(path=f"/{database}"))


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    """Run the Alembic CLI the same way an operator or the db-migrate Job does."""
    env = {**os.environ, "ALEMBIC_DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True,
    )


@pytest.fixture
def scratch_database():
    """A freshly created, empty database, dropped again afterwards."""
    import psycopg

    name = f"tm_migrations_{uuid.uuid4().hex[:12]}"
    admin = _with_database(TEST_POSTGRES_URL, "postgres")

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield _with_database(TEST_POSTGRES_URL, name)
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,)
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


def test_upgrade_head_builds_the_schema_from_empty(scratch_database):
    result = _alembic(scratch_database, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    import psycopg

    with psycopg.connect(_sync_url(scratch_database)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }

    assert {"candles", "candles_history", "exchanges", "symbols", "users"} <= tables


def test_models_have_not_drifted_from_the_migrations(scratch_database):
    """
    `alembic check` fails when the models declare something no migration
    creates. This is what stops a column added to a model from silently never
    reaching a deployed database — the exact failure mode create_all had.
    """
    assert _alembic(scratch_database, "upgrade", "head").returncode == 0

    result = _alembic(scratch_database, "check")
    assert result.returncode == 0, (
        "models and migrations have drifted — generate a revision with "
        f"`alembic revision --autogenerate`:\n{result.stdout}\n{result.stderr}"
    )


def test_upgrade_head_is_idempotent(scratch_database):
    assert _alembic(scratch_database, "upgrade", "head").returncode == 0
    second = _alembic(scratch_database, "upgrade", "head")
    assert second.returncode == 0, second.stderr


def test_baseline_downgrades_cleanly(scratch_database):
    """0001 must be reversible, so a bad first deploy can be rolled back."""
    assert _alembic(scratch_database, "upgrade", "0001_baseline").returncode == 0

    result = _alembic(scratch_database, "downgrade", "base")
    assert result.returncode == 0, result.stderr

    import psycopg

    with psycopg.connect(_sync_url(scratch_database)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }
    assert "candles" not in tables
    assert "users" not in tables


def test_a_legacy_create_all_database_converges_on_head(scratch_database):
    """
    The adoption path that matters: a database built by the pre-Alembic
    create_all — float prices, no unified-feed columns, no trace_id, the old
    3-column unique key, no users table — must reach head with a plain
    `alembic upgrade head` and no stamping, and end up drift-free.
    """
    import psycopg

    with psycopg.connect(_sync_url(scratch_database), autocommit=True) as conn:
        conn.execute(
            """
            CREATE TABLE candles (
                id SERIAL PRIMARY KEY, exchange VARCHAR NOT NULL, ticker VARCHAR NOT NULL,
                "interval" VARCHAR NOT NULL, "timestamp" TIMESTAMP NOT NULL,
                open_price DOUBLE PRECISION NOT NULL, high_price DOUBLE PRECISION NOT NULL,
                low_price DOUBLE PRECISION NOT NULL, close_price DOUBLE PRECISION NOT NULL,
                volume DOUBLE PRECISION NOT NULL,
                CONSTRAINT uq_candles_exchange_ticker_timestamp
                    UNIQUE (exchange, ticker, "timestamp"));
            CREATE INDEX ix_candles_exchange ON candles (exchange);
            CREATE INDEX ix_candles_ticker   ON candles (ticker);
            CREATE INDEX ix_candles_id       ON candles (id);
            CREATE TABLE candles_history (
                id SERIAL PRIMARY KEY, exchange VARCHAR NOT NULL, ticker VARCHAR NOT NULL,
                "interval" VARCHAR NOT NULL, trade_date DATE NOT NULL, "timestamp" TIMESTAMP NOT NULL,
                open_price DOUBLE PRECISION NOT NULL, high_price DOUBLE PRECISION NOT NULL,
                low_price DOUBLE PRECISION NOT NULL, close_price DOUBLE PRECISION NOT NULL,
                volume DOUBLE PRECISION NOT NULL, archived_at TIMESTAMP NOT NULL);
            CREATE INDEX ix_candles_history_exchange_ticker_date
                ON candles_history (exchange, ticker, trade_date);
            CREATE INDEX ix_candles_history_id ON candles_history (id);
            CREATE TABLE exchanges (
                id SERIAL PRIMARY KEY, name VARCHAR NOT NULL, method VARCHAR NOT NULL,
                enabled BOOLEAN NOT NULL, created_at TIMESTAMP NOT NULL,
                CONSTRAINT exchanges_name_key UNIQUE (name));
            CREATE INDEX ix_exchanges_id ON exchanges (id);
            CREATE TABLE symbols (
                id SERIAL PRIMARY KEY,
                exchange_id INTEGER NOT NULL
                    CONSTRAINT symbols_exchange_id_fkey REFERENCES exchanges(id),
                ticker VARCHAR NOT NULL, "interval" VARCHAR NOT NULL,
                enabled BOOLEAN NOT NULL, created_at TIMESTAMP NOT NULL,
                CONSTRAINT uq_symbol_exchange_ticker_interval
                    UNIQUE (exchange_id, ticker, "interval"));
            CREATE INDEX ix_symbols_id ON symbols (id);
            """
        )
        conn.execute(
            """
            INSERT INTO candles
                (exchange, ticker, "interval", "timestamp",
                 open_price, high_price, low_price, close_price, volume)
            VALUES ('binance', 'BTC/USDT', '1m', '2026-06-01 10:00:00',
                    65000.123456789, 65300, 64850, 65200, 15.4)
            """
        )

    result = _alembic(scratch_database, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    check = _alembic(scratch_database, "check")
    assert check.returncode == 0, f"{check.stdout}\n{check.stderr}"

    with psycopg.connect(_sync_url(scratch_database)) as conn:
        ticker, source_ticker, quote, fx, open_price = conn.execute(
            "SELECT ticker, source_ticker, quote_currency, fx_rate, open_price FROM candles"
        ).fetchone()
        assert (ticker, source_ticker, quote) == ("BTC/USD", "BTC/USDT", "USD")
        assert float(fx) == 1.0
        assert str(open_price) == "65000.12345679"      # float -> NUMERIC(28,8)

        constraints = {
            row[0]
            for row in conn.execute(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'candles'::regclass"
            ).fetchall()
        }
        assert "uq_candles_exchange_ticker_interval_timestamp" in constraints
        assert "uq_candles_exchange_ticker_timestamp" not in constraints

        assert conn.execute("SELECT to_regclass('public.users')").fetchone()[0] is not None
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'candles'"
            ).fetchall()
        }
        assert "trace_id" in columns
