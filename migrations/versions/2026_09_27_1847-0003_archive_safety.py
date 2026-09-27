"""archive safety — candles_history unique key, job_runs table

Two changes that together make the nightly archive safe to re-run:

1. A unique key on candles_history's natural key. The archive job inserted with
   a plain add_all against a table with no uniqueness at all, so re-running a
   date — or the CronJob's own backoffLimit retrying a failed run — appended a
   second full copy of the day. Existing duplicates are removed here first,
   keeping the earliest row per key, otherwise the constraint cannot be added.

2. job_runs, which records the outcome of each archive run so the API can
   export it to Prometheus. The scheduled job runs in a short-lived pod with no
   /metrics endpoint, so its counters were never scraped by anything.

Revision ID: 0003_archive_safety
Revises: 0002_legacy_alignment
Create Date: 2026-09-27 18:47:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_archive_safety"
down_revision: Union[str, None] = "0002_legacy_alignment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HISTORY_KEY = ("exchange", "ticker", "interval", "timestamp")
UNIQUE_NAME = "uq_candles_history_exchange_ticker_interval_timestamp"


def upgrade() -> None:
    # ── 1. De-duplicate before the constraint can exist ──────────────────────
    # Keeps the lowest id per natural key. The rows are byte-identical copies of
    # the same candle (the archive re-read the same source rows), so which one
    # survives doesn't matter; the earliest is kept for a stable archived_at.
    op.execute(
        """
        DELETE FROM candles_history
        WHERE id NOT IN (
            SELECT MIN(id) FROM candles_history
            GROUP BY exchange, ticker, "interval", "timestamp"
        )
        """
    )

    op.create_unique_constraint(UNIQUE_NAME, "candles_history", list(HISTORY_KEY))

    # `interval` added: every history query filters on it, so the old
    # (exchange, ticker, trade_date) index was only partially usable.
    op.drop_index(
        op.f("ix_candles_history_exchange_ticker_date"), table_name="candles_history"
    )
    op.create_index(
        "ix_candles_history_exchange_ticker_date",
        "candles_history",
        ["exchange", "ticker", "interval", "trade_date"],
        unique=False,
    )

    # ── 2. Job outcome log ───────────────────────────────────────────────────
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_name", sa.String(length=64), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rows_archived", sa.Integer(), nullable=False),
        sa.Column("rows_skipped", sa.Integer(), nullable=False),
        sa.Column("rows_deleted", sa.Integer(), nullable=False),
        sa.Column("files_written", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("job_runs_pkey")),
    )
    op.create_index(op.f("ix_job_runs_id"), "job_runs", ["id"], unique=False)
    op.create_index(
        "ix_job_runs_job_name_started_at", "job_runs", ["job_name", "started_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_job_runs_job_name_started_at", table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_id"), table_name="job_runs")
    op.drop_table("job_runs")

    op.drop_index("ix_candles_history_exchange_ticker_date", table_name="candles_history")
    op.create_index(
        op.f("ix_candles_history_exchange_ticker_date"),
        "candles_history",
        ["exchange", "ticker", "trade_date"],
        unique=False,
    )
    op.drop_constraint(UNIQUE_NAME, "candles_history", type_="unique")
    # The de-duplicated rows are not restored — they were exact duplicates.
