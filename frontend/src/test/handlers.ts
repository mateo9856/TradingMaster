import { HttpResponse, http } from "msw";

import type { Candle, Currencies, HistoryCandle, LiveCandle, Market, User } from "@/lib/types";

export function envelope<T>(data: T, message = "ok") {
  return { status: "success", message, data };
}

export const MARKETS: Market[] = [
  { ticker: "BTC/USD", asset_class: "crypto", exchanges: ["binance", "kraken"], intervals: ["30s", "1m", "1h"] },
  { ticker: "ETH/USD", asset_class: "crypto", exchanges: ["binance"], intervals: ["1m"] },
  { ticker: "PKN.WA/USD", asset_class: "stock", exchanges: ["yahoo"], intervals: ["1m", "1d"] },
];

export const CURRENCIES: Currencies = {
  default: "USD",
  currencies: [
    { code: "USD", name: "US dollar", units_per_usd: "1.00000000", rate_date: null },
    { code: "EUR", name: "Euro", units_per_usd: "0.89237908", rate_date: "2026-10-09" },
    { code: "PLN", name: "Polish złoty", units_per_usd: "3.91174371", rate_date: "2026-10-09" },
    { code: "NOK", name: "Norwegian krone", units_per_usd: "9.56228806", rate_date: "2026-10-09" },
  ],
};

export function candle(overrides: Partial<Candle> = {}): Candle {
  return {
    id: 1,
    exchange: "binance",
    ticker: "BTC/USD",
    interval: "1m",
    timestamp: "2026-09-19T12:00:00",
    open_price: "65000.00000000",
    high_price: "65300.00000000",
    low_price: "64850.00000000",
    close_price: "65200.00000000",
    volume: "15.40000000",
    source_ticker: "BTC/USDT",
    quote_currency: "USD",
    fx_rate: "0.99980000",
    ...overrides,
  };
}

export function historyCandle(overrides: Partial<HistoryCandle> = {}): HistoryCandle {
  return {
    ...candle(),
    trade_date: "2026-09-18",
    archived_at: "2026-09-19T23:30:00",
    ...overrides,
  };
}

export function liveCandle(overrides: Partial<LiveCandle> = {}): LiveCandle {
  return {
    schema_version: 2,
    exchange: "binance",
    ticker: "BTC/USD",
    source_ticker: "BTC/USDT",
    quote_currency: "USD",
    fx_rate: "0.99980000",
    interval: "1m",
    timestamp: "2026-09-19T12:01:00",
    open_price: "65200.00000000",
    high_price: "65400.00000000",
    low_price: "65150.00000000",
    close_price: "65350.00000000",
    volume: "3.20000000",
    ...overrides,
  };
}

export const USER: User = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "trader@example.com",
  is_active: true,
  is_superuser: false,
  is_verified: false,
};

export const handlers = [
  http.get("/api/v1/market/markets", () => HttpResponse.json(envelope(MARKETS))),
  http.get("/api/v1/currencies", () => HttpResponse.json(envelope(CURRENCIES))),
  http.get("/api/v1/market/candles/*", () => HttpResponse.json(envelope([candle()]))),
  http.get("/api/v1/history/*", () => HttpResponse.json(envelope([historyCandle()]))),
  http.get("/health", () => HttpResponse.json({ status: "ok" })),
  http.get("/metrics", () =>
    HttpResponse.text('kafka_messages_produced_total{exchange="binance"} 12\nfx_rate{quote="USDT"} 0.9997\n'),
  ),
  // Signed out by default — the session is a cookie the test's fetch never has.
  // Tests that need a signed-in user override this with `signedIn()`.
  http.get("/api/v1/users/me", () => HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })),
]

/** Handler override that makes the current visitor a signed-in user. */
export function signedIn(user: User = USER) {
  return http.get("/api/v1/users/me", () => HttpResponse.json(user));
};
