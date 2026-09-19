-- ─────────────────────────────────────────────────────────────────────────────
-- 2026-09 — multi-interval candles + unified USD price feed
--
-- Base.metadata.create_all() never alters existing tables, so any database
-- created before this change needs this script once. It is idempotent — safe
-- to run repeatedly:
--
--   psql "postgresql://user:mysecretpassword@localhost:5432/tradingmaster" \
--        -f scripts/migrations/2026_09_unified_feed.sql
--
-- What it does, for both `candles` and `candles_history`:
--   1. adds source_ticker / quote_currency / fx_rate columns
--   2. converts price + volume columns from DOUBLE PRECISION to NUMERIC(28,8)
--   3. (candles only) swaps the unique key to include `interval` — required by
--      the Flink upsert once several intervals are stored per market
--   4. backfills legacy rows to the unified ticker (BTC/USDT → BTC/USD,
--      source_ticker = BTC/USDT). Legacy USDT/USDC prices are kept as-is,
--      i.e. converted at the 1:1 peg (fx_rate = 1) — an approximation, as the
--      real USDT/USD rate at the time was never recorded. A legacy row whose
--      unified ticker would collide with an existing row is left unchanged.
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

-- 1. New columns ─────────────────────────────────────────────────────────────
ALTER TABLE candles         ADD COLUMN IF NOT EXISTS source_ticker  VARCHAR;
ALTER TABLE candles         ADD COLUMN IF NOT EXISTS quote_currency VARCHAR(8);
ALTER TABLE candles         ADD COLUMN IF NOT EXISTS fx_rate        NUMERIC(28, 8);
ALTER TABLE candles_history ADD COLUMN IF NOT EXISTS source_ticker  VARCHAR;
ALTER TABLE candles_history ADD COLUMN IF NOT EXISTS quote_currency VARCHAR(8);
ALTER TABLE candles_history ADD COLUMN IF NOT EXISTS fx_rate        NUMERIC(28, 8);

-- 2. Exact decimal prices ────────────────────────────────────────────────────
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

-- 3. Unique key includes interval ───────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_candles_exchange_ticker_interval_timestamp'
    ) THEN
        ALTER TABLE candles
            ADD CONSTRAINT uq_candles_exchange_ticker_interval_timestamp
            UNIQUE (exchange, ticker, "interval", "timestamp");
    END IF;
END $$;

ALTER TABLE candles DROP CONSTRAINT IF EXISTS uq_candles_exchange_ticker_timestamp;

-- 4. Backfill legacy rows to the unified ticker ────────────────────────────
-- One row per (exchange, base, interval, timestamp) is renamed — the USD
-- market wins over USDT, which wins over USDC — so renames never collide
-- with each other or with rows already on the unified ticker.
WITH candidates AS (
    SELECT
        id,
        split_part(ticker, '/', 1) || '/USD' AS new_ticker,
        row_number() OVER (
            PARTITION BY exchange, split_part(ticker, '/', 1), "interval", "timestamp"
            ORDER BY CASE split_part(ticker, '/', 2) WHEN 'USD' THEN 0 WHEN 'USDT' THEN 1 ELSE 2 END, id
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

-- History has no unique key — every legacy USD-equivalent row is renamed.
UPDATE candles_history
SET source_ticker  = ticker,
    ticker         = split_part(ticker, '/', 1) || '/USD',
    quote_currency = 'USD',
    fx_rate        = 1
WHERE source_ticker IS NULL
  AND split_part(ticker, '/', 2) IN ('USD', 'USDT', 'USDC');

COMMIT;
