"""Add per-user JWT revocation versions and producer coordination state.

Revision ID: 0009_auth_revocation
Revises: 0008_monitoring
Create Date: 2026-11-13 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_auth_revocation"
down_revision: Union[str, None] = "0008_monitoring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing JWTs without `ver` are treated as version 0; adding the column
    # with the same value preserves them until the first logout.
    op.add_column(
        "users",
        sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "producer_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instance_id", sa.String(length=36), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("duplicate_starts", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_table("producer_status")
    op.drop_column("users", "auth_version")
