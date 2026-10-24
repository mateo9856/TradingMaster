"""Persist per-user simulator accounts and purchase/funding payment records.

Revision ID: 0007_simulated_payments
Revises: 0006_development_trading
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_simulated_payments"
down_revision = "0006_development_trading"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing wallets, trades and ledger entries are deliberately untouched.
    # Accounts are seeded once on first authenticated access after upgrading.
    op.create_table(
        "trading_payment_accounts",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("trading_wallets.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(8), primary_key=True),
        sa.Column("balance", sa.Numeric(28, 8), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("balance >= 0", name=op.f("trading_payment_accounts_balance_nonnegative_check")),
        sa.CheckConstraint("kind IN ('debit', 'credit', 'paypal')", name=op.f("trading_payment_accounts_valid_kind_check")),
    )
    op.create_table(
        "trading_payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entry_id", sa.String(36), sa.ForeignKey("trading_credit_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trade_id", sa.String(36), sa.ForeignKey("trading_trades.id"), nullable=True),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("card_type", sa.String(6), nullable=True),
        sa.Column("amount", sa.Numeric(28, 8), nullable=False),
        sa.Column("wallet_delta", sa.Numeric(28, 8), nullable=False),
        sa.Column("account_balance_after", sa.Numeric(28, 8), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("entry_id", name=op.f("trading_payments_entry_id_key")),
        sa.UniqueConstraint("trade_id", name=op.f("trading_payments_trade_id_key")),
        sa.CheckConstraint("amount > 0", name=op.f("trading_payments_amount_positive_check")),
        sa.CheckConstraint("(method = 'card' AND card_type IS NOT NULL AND card_type IN ('debit', 'credit')) OR "
                           "(method IN ('credits', 'paypal') AND card_type IS NULL)",
                           name=op.f("trading_payments_valid_method_check")),
    )


def downgrade() -> None:
    op.drop_table("trading_payments")
    op.drop_table("trading_payment_accounts")
