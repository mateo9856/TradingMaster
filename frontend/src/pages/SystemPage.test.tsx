import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { SystemPage } from "./SystemPage";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

const METRICS = `
kafka_messages_produced_total{exchange="binance",ticker="BTC/USD",interval="1m"} 120.0
kafka_messages_produced_total{exchange="kraken",ticker="BTC/USD",interval="1m"} 80.0
websocket_active_connections{endpoint="live_candles"} 3.0
candles_skipped_total{exchange="coinbase"} 2.0
fx_rate_fallback_total{quote="USDT"} 5.0
fx_rate{quote="USDT"} 0.99973
`;

describe("health", () => {
  it("reports a healthy API", async () => {
    renderApp(<SystemPage />);

    expect(await screen.findByText("API healthy")).toBeInTheDocument();
  });

  it("reports an unreachable API", async () => {
    server.use(http.get("/health", () => HttpResponse.error()));

    renderApp(<SystemPage />);

    expect(await screen.findByText("API unreachable")).toBeInTheDocument();
  });
});

describe("metrics", () => {
  it("totals the counters and breaks them down per exchange", async () => {
    server.use(http.get("/metrics", () => HttpResponse.text(METRICS)));

    renderApp(<SystemPage />);

    expect(await screen.findByText("200")).toBeInTheDocument();   // 120 + 80 produced
    expect(screen.getByText("3")).toBeInTheDocument();            // live viewers
    expect(screen.getByText("▼ 2")).toBeInTheDocument();          // dropped candles, flagged
    expect(screen.getByText("▼ 5")).toBeInTheDocument();          // peg fallbacks, flagged
    expect(screen.getByText("120")).toBeInTheDocument();          // binance breakdown
    expect(screen.getByText("$0.99973000")).toBeInTheDocument();  // live USDT rate, always 8 decimals
  });

  it("says so when nothing has been collected yet", async () => {
    server.use(http.get("/metrics", () => HttpResponse.text("")));

    renderApp(<SystemPage />);

    expect(await screen.findByText(/Nothing collected yet/i)).toBeInTheDocument();
    expect(screen.getByText(/No live rate yet/i)).toBeInTheDocument();
  });

  it("degrades gracefully when metrics are switched off", async () => {
    server.use(http.get("/metrics", () => new HttpResponse(null, { status: 404 })));

    renderApp(<SystemPage />);

    expect(await screen.findByText(/Metrics unavailable/i)).toBeInTheDocument();
  });
});
