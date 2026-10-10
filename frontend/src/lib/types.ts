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

export type AssetClass = "crypto" | "stock";

/** One unified market: GET /api/v1/market/markets */
export interface Market {
  ticker: string;        // "BTC/USD", "PKN.WA/USD"
  asset_class?: AssetClass; // absent from older APIs — treat as crypto
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
  quote_currency: string | null; // the currency the prices are in — "USD" unless ?currency= was asked
  fx_rate: string | null;        // native quote → USD rate applied
  currency_rate?: string | null; // USD → quote_currency ECB rate (absent for USD)
  rate_date?: string | null;     // publication date of currency_rate, "2026-10-09"
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
  currency_rate?: string | null;
  rate_date?: string | null;
}

/** One display currency: GET /api/v1/currencies */
export interface CurrencyInfo {
  code: string;                 // "PLN"
  name: string;                 // "Polish złoty"
  units_per_usd: string | null; // latest ECB rate, "3.91174371"
  rate_date: string | null;
}

export interface Currencies {
  default: string;              // server DEFAULT_CURRENCY
  currencies: CurrencyInfo[];
}

export interface User {
  id: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
  preferred_currency?: string | null;
}

export const INTERVALS = ["30s", "1m", "5m", "1h", "1d"] as const;
export type Interval = (typeof INTERVALS)[number];
