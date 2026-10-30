export type AssetClass = "crypto" | "stock";

/**
 * One unified market: GET /api/v1/market/markets?lang=…
 *
 * Besides what is collected (exchanges, intervals), it says what the
 * instrument *is*, in the requested language. Names are proper nouns and never
 * translated; labels and descriptions are. The descriptive fields are optional
 * so an older API (or a test fixture) without them still works.
 */
export interface Market {
  ticker: string;             // "BTC/USD", "PKN.WA/USD"
  asset_class?: AssetClass;   // absent from older APIs — treat as crypto
  exchanges: string[];        // ["binance", "kraken"]
  intervals: string[];        // ["30s", "1m", "5m", "1h", "1d"]
  symbol?: string;            // "BTC", "PKN.WA"
  name?: string;              // "Bitcoin", "ORLEN S.A."
  short_name?: string;        // "Bitcoin", "Orlen"
  slug?: string;              // "bitcoin-btc" — the market page URL
  asset_class_label?: string; // "Cryptocurrency" / "Kryptowaluta"
  category?: string | null;
  category_label?: string | null;
  venue?: string | null;      // "GPW"
  venue_label?: string | null;
  country?: string | null;
  ticker_symbol?: string | null; // "WSE:PKN"
  description?: string;
  page_title?: string;
  page_description?: string;
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

export const INTERVALS = ["30s", "1m", "5m", "1h", "1d"] as const;
export type Interval = (typeof INTERVALS)[number];
