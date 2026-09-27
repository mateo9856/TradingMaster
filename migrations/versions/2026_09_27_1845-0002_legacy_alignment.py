"""legacy alignment — unified feed columns, exact decimals, trace_id

Reconciles a database that was built by the pre-Alembic
Base.metadata.create_all with what the models declare today. create_all creates
missing tables but never alters existing ones, so anything deployed before the
unified feed landed is missing columns, still stores prices as floats, and
carries the old 3-column unique key.

Everything here is idempotent and a no-op on a database revision 0001 just
created, so both the fresh and the legacy path converge on `alembic upgrade
head` with no stamping.

Ports scripts/migrations/2026_09_unified_feed.sql, plus the two gaps that
script never covered and the README documented as manual DDL:
candles.trace_id and the users table (the latter is handled by 0001's guard).

PostgreSQL only. On any other dialect the tables can only have come from 0001,
which already creates them in their final shape, so this revision returns early.

Revision ID: 0002_legacy_alignment
Revises: 0001_baseline
Create Date: 2026-09-27 18:45:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_legacy_alignment"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRICE_COLUMNS = ("open_price", "high_price", "low_price", "close_price", "volume")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # 1. Unified-feed columns, and the trace_id that only ever arrived via
    #    create_all on a fresh database (README:340 called this out as manual).
    op.execute("ALTER TABLE candles         ADD COLUMN IF NOT EXISTS source_ticker  VARCHAR")
    op.execute("ALTER TABLE candles         ADD COLUMN IF NOT EXISTS quote_currency VARCHAR(8)")
    op.execute("ALTER TABLE candles         ADD COLUMN IF NOT EXISTS fx_rate        NUMERIC(28, 8)")
    op.execute("ALTER TABLE candles         ADD COLUMN IF NOT EXISTS trace_id       VARCHAR(32)")
    op.execute("ALTER TABLE candles_history ADD COLUMN IF NOT EXISTS source_ticker  VARCHAR")
    op.execute("ALTER TABLE candles_history ADD COLUMN IF NOT EXISTS quote_currency VARCHAR(8)")
    op.execute("ALTER TABLE candles_history ADD COLUMN IF NOT EXISTS fx_rate        NUMERIC(28, 8)")

    # 2. Exact decimal prices — DOUBLE PRECISION → NUMERIC(28, 8).
    op.execute(
        """
        DO $$
        DECLARE
            tbl TEXT;
            col TEXT;
        BEGIN
            FOREACH tbl IN ARRAY ARRAY['candles', 'candles_history'] LOOP
                FOREACH col IN ARRAY ARRAY['open_price', 'high_price', 'low_price', 'close_price', 'volume'] LOOP
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = tbl AND column_name = col AND data_type <> 'numeric'
                    ) THEN
                        EXECUTE format(
                            'ALTER TABLE %I ALTER COLUMN %I TYPE NUMERIC(28, 8) USING round(%I::numeric, 8)',
                            tbl, col, col
                        );
                    END IF;
                END LOOP;
            END LOOP;
        END $$;
        """
    )

    # 3. The unique key must include `interval` — the Flink sink's
    #    ON CONFLICT ... DO UPDATE targets it once several intervals per market
    #    are stored.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_candles_exchange_ticker_interval_timestamp'
            ) THEN
                ALTER TABLE candles
                    ADD CONSTRAINT uq_candles_exchange_ticker_interval_timestamp
                    UNIQUE (exchange, ticker, "interval", "timestamp");
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE candles DROP CONSTRAINT IF EXISTS uq_candles_exchange_ticker_timestamp")

    # 4. Backfill legacy rows to the unified ticker. One row per
    #    (exchange, base, interval, timestamp) is renamed — USD beats USDT beats
    #    USDC — so renames collide neither with each other nor with rows already
    #    on the unified ticker. Legacy stablecoin prices are kept as-is, i.e.
    #    converted at the 1:1 peg (fx_rate = 1): the real rate at the time was
    #    never recorded. See docs/BUSINESS_SUMMARY.md section 8.
    op.execute(
        """
        WITH candidates AS (
            SELECT
                id,
                split_part(ticker, '/', 1) || '/USD' AS new_ticker,
                row_number() OVER (
                    PARTITION BY exchange, split_part(ticker, '/', 1), "interval", "timestamp"
                    ORDER BY CASE split_part(ticker, '/', 2)
                                 WHEN 'USD' THEN 0 WHEN 'USDT' THEN 1 ELSE 2 END, id
                ) AS rn
            FROM candles
            WHERE source_ticker IS NULL
              AND split_part(ticker, '/', 2) IN ('USD', 'USDT', 'USDC')
        )
        UPDATE candles AS c
        SET source_ticker  = c.ticker,
            ticker         = cand.new_ticker,
            quote_currency = 'USD',
            fx_rate        = 1
        FROM candidates AS cand
        WHERE c.id = cand.id
          AND cand.rn = 1
          AND NOT EXISTS (
              SELECT 1 FROM candles AS other
              WHERE other.exchange    = c.exchange
                AND other.ticker      = cand.new_ticker
                AND other."interval"  = c."interval"
                AND other."timestamp" = c."timestamp"
                AND other.id         <> c.id
          );
        """
    )

    # History has no unique key, so every legacy USD-equivalent row is renamed.
    op.execute(
        """
        UPDATE candles_history
        SET source_ticker  = ticker,
            ticker         = split_part(ticker, '/', 1) || '/USD',
            quote_currency = 'USD',
            fx_rate        = 1
        WHERE source_ticker IS NULL
          AND split_part(ticker, '/', 2) IN ('USD', 'USDT', 'USDC');
        """
    )


def downgrade() -> None:
    """
    Not reversible. The ticker backfill overwrites `ticker` in place and the
    float→numeric conversion loses nothing but cannot identify which rows were
    converted, so there is no honest way back. Recover from a backup instead.
    """
    raise NotImplementedError(
        "0002_legacy_alignment is a one-way data migration — restore from a backup instead."
    )
