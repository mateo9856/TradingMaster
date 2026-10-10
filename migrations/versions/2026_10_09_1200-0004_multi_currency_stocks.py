"""multi-currency and stocks — fiat_rates, exchanges.asset_class, users.preferred_currency

1. fiat_rates: ECB daily reference rates, as units per 1 USD. Prices stay
   stored in USD; the API converts to the reader's currency with these, and the
   producer converts fiat-quoted markets (Warsaw stocks in PLN) to USD.
2. exchanges.asset_class: "crypto" (every existing row) or "stock" (the Yahoo
   Finance source), so the UI can group markets.
3. users.preferred_currency: the display currency a user picked; NULL means
   "detect it from the browser".

Revision ID: 0004_multi_currency_stocks
Revises: 0003_archive_safety
Create Date: 2026-10-09 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_multi_currency_stocks"
down_revision: Union[str, None] = "0003_archive_safety"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fiat_rates",
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("units_per_usd", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.PrimaryKeyConstraint("rate_date", "currency", name=op.f("fiat_rates_pkey")),
    )

    op.add_column(
        "exchanges",
        sa.Column("asset_class", sa.String(length=16), nullable=False, server_default="crypto"),
    )

    op.add_column("users", sa.Column("preferred_currency", sa.String(length=3), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "preferred_currency")
    op.drop_column("exchanges", "asset_class")
    op.drop_table("fiat_rates")
