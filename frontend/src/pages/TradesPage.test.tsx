import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { CheckoutForm } from "./CheckoutPage";
import { TradeConfirmation } from "@/components/TradeConfirmation";
import type { Trade, TradingQuote } from "@/lib/trading";
import { envelope, signedIn } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";
import { TradesPage } from "./TradesPage";

const prefix = "/api/v1/trading";
const trade: Trade = {
  id: "trade-1", exchange: "kraken", ticker: "BTC/USD", quantity: "1.00000000",
  buy_price: "100.00000000", cost: "100.00000000", status: "open",
  opened_at: "2026-10-22T12:00:00Z", closed_at: null, proceeds: null, realized_pnl: null,
  valuation: { bid: "99.00000000", ask: "100.00000000", spread: "1.00000000", spread_percent: "1.00502513",
    sell_value: "99.00000000", unrealized_pnl: "-1.00000000", pnl_percent: "-1.00000000", delayed: false,
    source_at: "2026-10-22T12:00:00Z", received_at: "2026-10-22T12:00:00Z" },
};
const quote = (side: "buy" | "sell" = "buy"): TradingQuote => ({
  id: "quote-1", side, exchange: "kraken", ticker: "BTC/USD", source_ticker: "BTC/USD",
  quantity: "1.00000000", amount: side === "buy" ? "100.00000000" : "99.00000000",
  bid: "99.00000000", ask: "100.00000000", spread: "1.00000000", spread_percent: "1.00502513",
  source_at: "2026-10-22T12:00:00Z", received_at: new Date().toISOString(),
  expires_at: new Date(Date.now() + 15_000).toISOString(), delayed: false, trade_id: side === "sell" ? trade.id : null,
});

beforeEach(() => {
  server.use(
    signedIn(),
    http.get(prefix + "/capabilities", () => HttpResponse.json(envelope({ enabled: true, simulated: true }))),
    http.post(prefix + "/wallet/initialize", () => HttpResponse.json(envelope({ balance: "1000.00000000", currency: "credits" }))),
    http.get(prefix + "/trades", () => HttpResponse.json(envelope({ items: [trade], total: 1, limit: 10, offset: 0 }))),
    http.post(prefix + "/quotes", async ({ request }) => {
      const body = await request.json() as { side: "buy" | "sell" };
      return HttpResponse.json(envelope(quote(body.side)));
    }),
  );
});

describe("buying with credits", () => {
  it("previews bid/ask and confirms a server quote with CSRF and idempotency headers", async () => {
    let executed: unknown;
    server.use(http.post(prefix + "/quotes", async ({ request }) => {
      expect(await request.json()).toEqual({ side: "buy", ticker: "BTC/USD", exchange: "kraken", budget: "100" });
      return HttpResponse.json(envelope(quote()));
    }));
    server.use(http.post(prefix + "/trades", async ({ request }) => {
      executed = await request.json();
      expect(request.headers.get("Idempotency-Key")).toMatch(/^[a-f0-9-]{36}$/);
      expect(request.headers.get("X-Requested-With")).toBeTruthy();
      return HttpResponse.json(envelope({ trade, wallet: { balance: "900.00000000" } }));
    }));
    renderApp(<CheckoutForm ticker="BTC/USD" exchange="kraken" />);
    await screen.findByText("Simulated TradingMaster balance: 1000.00 credits");
    await userEvent.click(screen.getByRole("button", { name: "Preview purchase" }));
    expect(await screen.findByText("Bid (sell price)")).toBeInTheDocument();
    expect(screen.getByText("Ask (buy price)")).toBeInTheDocument();
    expect(screen.getAllByText("BTC/USD · Kraken")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Confirm purchase" }));
    expect(await screen.findByText("Purchase completed.")).toBeInTheDocument();
    expect(executed).toEqual({ quote_id: "quote-1", payment_method: "credits" });
  });

  it("shows provider errors", async () => {
    server.use(http.post(prefix + "/quotes", () => HttpResponse.json({ detail: "Provider quote is stale" }, { status: 503 })));
    renderApp(<CheckoutForm ticker="BTC/USD" exchange="kraken" />);
    await screen.findByText("Simulated TradingMaster balance: 1000.00 credits");
    await userEvent.click(screen.getByRole("button", { name: "Preview purchase" }));
    expect(await screen.findByText("Provider quote is stale")).toBeInTheDocument();
  });

  it("keeps the same idempotency key when retrying an uncertain purchase", async () => {
    const keys: string[] = [];
    server.use(http.post(prefix + "/trades", ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key")!);
      return keys.length === 1 ? HttpResponse.error() : HttpResponse.json(envelope({ trade }));
    }));
    renderApp(<CheckoutForm ticker="BTC/USD" exchange="kraken" />);
    await screen.findByText("Simulated TradingMaster balance: 1000.00 credits");
    await userEvent.click(screen.getByRole("button", { name: "Preview purchase" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirm purchase" }));
    await screen.findByText("Failed to fetch");
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm purchase" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Confirm purchase" }));
    await screen.findByText("Purchase completed.");
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it("disables an expired confirmation", () => {
    renderApp(<TradeConfirmation quote={{ ...quote(), expires_at: new Date(Date.now() - 1000).toISOString() }} busy={false} onConfirm={() => {}} onCancel={() => {}} />);
    expect(screen.getByRole("button", { name: "Confirm purchase" })).toBeDisabled();
    expect(screen.getByText(/Quote expired/)).toBeInTheDocument();
  });
});

describe("My Trades", () => {
  it("shows spread-adjusted losses, confirms a full sale, and links to funding", async () => {
    let sold = false;
    server.use(http.post(prefix + "/trades/:id/sell", ({ request }) => {
      expect(request.headers.get("Idempotency-Key")).toBeTruthy(); sold = true;
      return HttpResponse.json(envelope({ trade: { ...trade, status: "closed" } }));
    }));
    renderApp(<TradesPage />);
    expect(await screen.findByText("Unrealized profit / loss: -1.00 credits")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "BTC/USD · Kraken" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add funds" })).toHaveAttribute("href", "/wallet");
    await userEvent.click(screen.getByRole("button", { name: "Sell entire trade" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirm full sale" }));
    expect(await screen.findByText("Trade sold.")).toBeInTheDocument();
    expect(sold).toBe(true);
    expect(document.head.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe("noindex, nofollow");
  });

  it("replaces unrestricted demo funding with the wallet flow", async () => {
    renderApp(<TradesPage />);
    await screen.findByText(/1000.00 credits/);
    expect(screen.getByRole("link", { name: "Add funds" })).toHaveAttribute("href", "/wallet");
    expect(screen.queryByRole("button", { name: "Add demo credits" })).not.toBeInTheDocument();
  });

  it("shows missing valuations as unknown and disables selling", async () => {
    server.use(http.get(prefix + "/trades", () => HttpResponse.json(envelope({ items: [{ ...trade, valuation: null, valuation_error: "Stock market is closed" }], total: 1, limit: 10 }))));
    renderApp(<TradesPage />);
    expect(await screen.findByText(/Valuation unavailable: Stock market is closed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sell entire trade" })).toBeDisabled();
    expect(screen.getByText("Unrealized profit / loss: — credits")).toBeInTheDocument();
  });

  it("hides the feature when development trading is disabled", async () => {
    server.use(http.get(prefix + "/capabilities", () => HttpResponse.json(envelope({ enabled: false }))));
    renderApp(<TradesPage />);
    expect(await screen.findByText("Simulated trading is disabled.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add demo credits" })).not.toBeInTheDocument();
  });
});
