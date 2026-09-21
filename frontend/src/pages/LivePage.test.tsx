import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LivePage } from "./LivePage";
import { FakeWebSocket, installFakeWebSocket } from "@/test/fake-websocket";
import { MARKETS, candle, envelope, liveCandle } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

// The chart needs a real canvas; its own conversion logic is covered in
// src/lib/chart-data.test.ts, so the screen tests stub the component.
vi.mock("@/components/CandleChart", () => ({
  CandleChart: ({ candles, liveCandle: live }: { candles: unknown[]; liveCandle: unknown }) => (
    <div data-testid="candle-chart" data-count={candles.length} data-live={live ? "yes" : "no"} />
  ),
}));

afterEach(() => vi.unstubAllGlobals());

describe("loading markets", () => {
  it("shows the first market with its exchanges and intervals", async () => {
    installFakeWebSocket();

    renderApp(<LivePage />);

    expect(await screen.findByTestId("candle-chart")).toBeInTheDocument();
    expect(screen.getByLabelText("Market")).toHaveValue("BTC/USD");
    expect(screen.getByLabelText("Exchange")).toHaveValue("binance");
    expect(within(screen.getByLabelText("Interval")).getAllByRole("option").map((o) => o.textContent))
      .toEqual(MARKETS[0].intervals);
  });

  it("explains an empty market list instead of rendering an empty chart", async () => {
    installFakeWebSocket();
    server.use(http.get("/api/v1/market/markets", () => HttpResponse.json(envelope([]))));

    renderApp(<LivePage />);

    expect(await screen.findByText(/No markets configured/i)).toBeInTheDocument();
  });

  it("tells the user the API is down", async () => {
    installFakeWebSocket();
    server.use(http.get("/api/v1/market/markets", () => HttpResponse.error()));

    renderApp(<LivePage />);

    expect(await screen.findByText(/Cannot reach the API/i)).toBeInTheDocument();
  });
});

describe("candles", () => {
  it("shows the last price and the conversion applied", async () => {
    installFakeWebSocket();

    renderApp(<LivePage />);

    expect(await screen.findByText("Last price")).toBeInTheDocument();
    expect(screen.getByText("▲ $65,200.00")).toBeInTheDocument();
    expect(screen.getByText("USD conversion")).toBeInTheDocument();
    expect(screen.getByText("0.99980000")).toBeInTheDocument();
    expect(screen.getByText(/trades this as BTC\/USDT/)).toBeInTheDocument();
  });

  it("explains a 404 as 'nothing stored yet', not an error", async () => {
    installFakeWebSocket();
    server.use(
      http.get("/api/v1/market/candles/*", () =>
        HttpResponse.json({ detail: "Ticker BTC/USD not found" }, { status: 404 }),
      ),
    );

    renderApp(<LivePage />);

    expect(await screen.findByText(/No candles stored yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId("candle-chart")).not.toBeInTheDocument();
  });

  it("reloads when another interval is chosen", async () => {
    installFakeWebSocket();
    const requested: string[] = [];
    server.use(
      http.get("/api/v1/market/candles/*", ({ request }) => {
        requested.push(new URL(request.url).searchParams.get("interval") ?? "");
        return HttpResponse.json(envelope([candle()]));
      }),
    );
    renderApp(<LivePage />);
    await screen.findByTestId("candle-chart");

    await userEvent.selectOptions(screen.getByLabelText("Interval"), "1h");

    await waitFor(() => expect(requested).toContain("1h"));
  });
});

describe("live stream", () => {
  it("shows the raw message once one arrives", async () => {
    installFakeWebSocket();
    renderApp(<LivePage />);
    await screen.findByTestId("candle-chart");

    await waitFor(() => expect(FakeWebSocket.instances.length).toBeGreaterThan(0));
    FakeWebSocket.last.open();
    FakeWebSocket.last.emit(liveCandle());

    expect(await screen.findByText(/"source_ticker": "BTC\/USDT"/)).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("surfaces a rejected market (close code 1008)", async () => {
    installFakeWebSocket();
    renderApp(<LivePage />);
    await screen.findByTestId("candle-chart");

    await waitFor(() => expect(FakeWebSocket.instances.length).toBeGreaterThan(0));
    FakeWebSocket.last.serverClose(1008, "Unknown market BTCUSD");

    expect(await screen.findByText(/Live stream rejected/i)).toBeInTheDocument();
    expect(screen.getByText("Unknown market BTCUSD")).toBeInTheDocument();
  });
});

describe("defaults", () => {
  it("opens on Bitcoin, not on whatever sorts first", async () => {
    installFakeWebSocket();
    server.use(
      http.get("/api/v1/market/markets", () =>
        HttpResponse.json(
          envelope([
            { ticker: "ADA/USD", exchanges: ["binance"], intervals: ["1m"] },
            { ticker: "BTC/USD", exchanges: ["binance"], intervals: ["1m"] },
          ]),
        ),
      ),
    );

    renderApp(<LivePage />);

    expect(await screen.findByLabelText("Market")).toHaveValue("BTC/USD");
  });

  it("falls back to the first market when Bitcoin isn't collected", async () => {
    installFakeWebSocket();
    server.use(
      http.get("/api/v1/market/markets", () =>
        HttpResponse.json(envelope([{ ticker: "SOL/USD", exchanges: ["kraken"], intervals: ["5m"] }])),
      ),
    );

    renderApp(<LivePage />);

    expect(await screen.findByLabelText("Market")).toHaveValue("SOL/USD");
  });
});
