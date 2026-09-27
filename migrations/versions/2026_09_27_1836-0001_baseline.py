"""baseline schema

The schema as it stood when Alembic was introduced: candles, candles_history,
exchanges, symbols, users.

Every create_table is guarded by a has_table() check. Before this revision the
schema came from Base.metadata.create_all at API startup, which creates missing
tables but never alters existing ones — so deployed databases exist in several
different shapes (some predating candles.trace_id, some with no users table at
all). Guarding the baseline lets every one of them run `alembic upgrade head`
without an operator first deciding whether to `alembic stamp`; revision 0002
then reconciles whatever an older create_all left behind.

This is a one-time concession for the baseline. Later revisions are ordinary
unguarded migrations.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-27 18:36:25.331915
"""

from typing import Sequence, Union

import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("candles"):
        op.create_table(
            "candles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("exchange", sa.String(), nullable=False),
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("interval", sa.String(), nullable=False),
            sa.Column("timestamp", sa.DateTime(), nullable=False),
            sa.Column("open_price", sa.Numeric(precision=28, scale=8), nullable=False),
            sa.Column("high_price", sa.Numeric(precision=28, scale=8), nullable=False),
            sa.Column("low_price", sa.Numeric(precision=28, scale=8), nullable=False),
            sa.Column("close_price", sa.Numeric(precision=28, scale=8), nullable=False),
            sa.Column("volume", sa.Numeric(precision=28, scale=8), nullable=False),
            sa.Column("source_ticker", sa.String(), nullable=True),
            sa.Column("quote_currency", sa.String(length=8), nullable=True),
            sa.Column("fx_rate", sa.Numeric(precision=28, scale=8), nullable=True),
            sa.Column("trace_id", sa.String(length=32), nullable=True),
            sa.PrimaryKeyConstraint("id", name=op.f("candles_pkey")),
            sa.UniqueConstraint(
                "exchange", "ticker", "interval", "timestamp",
                name="uq_candles_exchange_ticker_interval_timestamp",
            ),
        )
        op.create_index(op.f("ix_candles_exchange"), "candles", ["exchange"], unique=False)
        op.create_index(op.f("ix_candles_id"), "candles", ["id"], unique=False)
        op.create_index(op.f("ix_candles_ticker"), "candles", ["ticker"], unique=False)

    if not _has_table("candles_history"):
        op.create_table(
            "candles_history",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("exchange", sa.String(), nullable=False),
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("interval", sa.String(), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("timestamp", sa.DateTime(), nullable=False),
            sa.Column("open_price", sa.Numeric(precision=28, scale=8), nullable=False),
            sa.Column("high_price", sa.Numeric(precision=28, scale=8), nullable=False),
            sa.Column("low_price", sa.Numeric(precision=28, scale=8), nullable=False),
            sa.Column("close_price", sa.Numeric(precision=28, scale=8), nullable=False),
            sa.Column("volume", sa.Numeric(precision=28, scale=8), nullable=False),
            sa.Column("source_ticker", sa.String(), nullable=True),
            sa.Column("quote_currency", sa.String(length=8), nullable=True),
            sa.Column("fx_rate", sa.Numeric(precision=28, scale=8), nullable=True),
            sa.Column("archived_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id", name=op.f("candles_history_pkey")),
        )
        op.create_index(
            "ix_candles_history_exchange_ticker_date",
            "candles_history", ["exchange", "ticker", "trade_date"], unique=False,
        )
        op.create_index(op.f("ix_candles_history_id"), "candles_history", ["id"], unique=False)

    if not _has_table("exchanges"):
        op.create_table(
            "exchanges",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("method", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id", name=op.f("exchanges_pkey")),
            sa.UniqueConstraint("name", name=op.f("exchanges_name_key")),
        )
        op.create_index(op.f("ix_exchanges_id"), "exchanges", ["id"], unique=False)

    if not _has_table("symbols"):
        op.create_table(
            "symbols",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("exchange_id", sa.Integer(), nullable=False),
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("interval", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["exchange_id"], ["exchanges.id"], name=op.f("symbols_exchange_id_fkey"),
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("symbols_pkey")),
            sa.UniqueConstraint(
                "exchange_id", "ticker", "interval", name="uq_symbol_exchange_ticker_interval",
            ),
        )
        op.create_index(op.f("ix_symbols_id"), "symbols", ["id"], unique=False)

    # Added with the cookie auth backend; older databases predate it entirely
    # (README documented a manual CREATE TABLE until this revision).
    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("hashed_password", sa.String(length=1024), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("is_superuser", sa.Boolean(), nullable=False),
            sa.Column("is_verified", sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint("id", name=op.f("users_pkey")),
        )
        op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_symbols_id"), table_name="symbols")
    op.drop_table("symbols")
    op.drop_index(op.f("ix_exchanges_id"), table_name="exchanges")
    op.drop_table("exchanges")
    op.drop_index(op.f("ix_candles_history_id"), table_name="candles_history")
    op.drop_index("ix_candles_history_exchange_ticker_date", table_name="candles_history")
    op.drop_table("candles_history")
    op.drop_index(op.f("ix_candles_ticker"), table_name="candles")
    op.drop_index(op.f("ix_candles_id"), table_name="candles")
    op.drop_index(op.f("ix_candles_exchange"), table_name="candles")
    op.drop_table("candles")
