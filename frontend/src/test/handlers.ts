import { HttpResponse, http } from "msw";

import type { Candle, HistoryCandle, LiveCandle, Market, User } from "@/lib/types";

export function envelope<T>(data: T, message = "ok") {
  return { status: "success", message, data };
}

export const MARKETS: Market[] = [
  { ticker: "BTC/USD", exchanges: ["binance", "kraken"], intervals: ["30s", "1m", "1h"] },
  { ticker: "ETH/USD", exchanges: ["binance"], intervals: ["1m"] },
];

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
