"""Development paper trading wallets, quote snapshots, executions and ledger.

Revision ID: 0006_development_trading
Revises: 0005_instruments
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_development_trading"
down_revision = "0005_instruments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_dev_guest", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "trading_wallets",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("balance", sa.Numeric(28, 8), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("balance >= 0", name=op.f("trading_wallets_balance_nonnegative_check")),
    )
    op.create_table(
        "trading_quotes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("exchange", sa.String(64), nullable=False),
        sa.Column("ticker", sa.String(40), nullable=False),
        sa.Column("source_ticker", sa.String(40), nullable=False),
        sa.Column("trade_id", sa.String(36), nullable=True),
        sa.Column("bid", sa.Numeric(28, 8), nullable=False),
        sa.Column("ask", sa.Numeric(28, 8), nullable=False),
        sa.Column("fx_rate", sa.Numeric(28, 8), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("amount", sa.Numeric(28, 8), nullable=False),
        sa.Column("source_at", sa.DateTime(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("delayed", sa.Boolean(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_trading_quotes_user_id", "trading_quotes", ["user_id"])
    op.create_table(
        "trading_trades",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exchange", sa.String(64), nullable=False),
        sa.Column("ticker", sa.String(40), nullable=False),
        sa.Column("source_ticker", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("buy_price", sa.Numeric(28, 8), nullable=False),
        sa.Column("cost", sa.Numeric(28, 8), nullable=False),
        sa.Column("buy_quote_id", sa.String(36), sa.ForeignKey("trading_quotes.id"), nullable=False, unique=True),
        sa.Column("sell_quote_id", sa.String(36), sa.ForeignKey("trading_quotes.id"), nullable=True, unique=True),
        sa.Column("sell_price", sa.Numeric(28, 8), nullable=True),
        sa.Column("proceeds", sa.Numeric(28, 8), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("quantity > 0 AND cost > 0", name=op.f("trading_trades_positive_purchase_check")),
    )
    op.create_index("ix_trading_trades_user_id", "trading_trades", ["user_id"])
    op.create_table(
        "trading_credit_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("trading_wallets.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(28, 8), nullable=False),
        sa.Column("balance_after", sa.Numeric(28, 8), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "request_key", name="uq_credit_user_request"),
    )


def downgrade() -> None:
    op.drop_table("trading_credit_entries")
    op.drop_index("ix_trading_trades_user_id", table_name="trading_trades")
    op.drop_table("trading_trades")
    op.drop_index("ix_trading_quotes_user_id", table_name="trading_quotes")
    op.drop_table("trading_quotes")
    op.drop_table("trading_wallets")
    op.drop_column("users", "is_dev_guest")
