/**
 * Mirrors the FastAPI response schemas (app/schemas/*.py).
 *
 * Every price and volume is an exact decimal **string** with 8 decimals
 * ("65000.10000000") — the unified feed's number format. Keep them as strings
 * everywhere except where a number is genuinely needed (charting, maths), and
 * convert there with `toNumber` from ./format.
 */

export interface ApiResponse<T> {
  status: string;
  message: string | null;
  data: T;
}

/** One unified market: GET /api/v1/market/markets */
export interface Market {
  ticker: string;        // "BTC/USD"
  exchanges: string[];   // ["binance", "kraken"]
  intervals: string[];   // ["30s", "1m", "5m", "1h", "1d"]
}

export interface Candle {
  id: number;
  exchange: string;
  ticker: string;
  interval: string;
  timestamp: string;             // naive UTC, "2026-09-19T18:22:00"
  open_price: string;
  high_price: string;
  low_price: string;
  close_price: string;
  volume: string;
  source_ticker: string | null;  // the exchange's own market, "BTC/USDT"
  quote_currency: string | null; // always "USD" for collected rows
  fx_rate: string | null;        // native quote → USD rate applied
}

export interface HistoryCandle extends Omit<Candle, "id"> {
  id: number;
  trade_date: string;
  archived_at: string;
}

/** A live candle as it arrives on the WebSocket — no `id`, plus `schema_version`. */
export interface LiveCandle {
  schema_version: number;
  exchange: string;
  ticker: string;
  source_ticker: string;
  quote_currency: string;
  fx_rate: string;
  interval: string;
  timestamp: string;
  open_price: string;
  high_price: string;
  low_price: string;
  close_price: string;
  volume: string;
}

export interface User {
  id: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
}

export const INTERVALS = ["30s", "1m", "5m", "1h", "1d"] as const;
export type Interval = (typeof INTERVALS)[number];
