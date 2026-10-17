"""instruments — names and classification for markets

One row per unified base symbol ("BTC", "PKN.WA"): the proper name, a short
name, the URL slug of its market page, and its classification. Seeded from
app/helpers/instruments.py at startup; editable through the API.

Revision ID: 0005_instruments
Revises: 0004_multi_currency_stocks
Create Date: 2026-10-11 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_instruments"
down_revision: Union[str, None] = "0004_multi_currency_stocks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("short_name", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("asset_class", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("venue", sa.String(length=16), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("symbol", name=op.f("instruments_pkey")),
        sa.UniqueConstraint("slug", name=op.f("instruments_slug_key")),
    )


def downgrade() -> None:
    op.drop_table("instruments")
