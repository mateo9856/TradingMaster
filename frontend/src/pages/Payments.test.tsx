import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse, http } from "msw";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/AppShell";
import { PurchasePanel } from "@/components/PurchasePanel";
import { useAuth } from "@/lib/auth";
import { activateLanguage } from "@/lib/i18n";
import { USER, envelope, signedIn } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";
import { CheckoutForm, CheckoutPage } from "./CheckoutPage";
import { WalletPage } from "./WalletPage";
import { TradesPage } from "./TradesPage";

const prefix = "/api/v1/trading";
let balance: string;
let quoteCount: number;
const quote = (expired = false) => ({
  id: `quote-${++quoteCount}`, side: "buy", exchange: "kraken", ticker: "BTC/USD", source_ticker: "BTC/USD",
  quantity: "1.00000000", amount: "100.00000000", bid: "99.00000000", ask: "100.00000000",
  spread: "1.00000000", spread_percent: "1.00502513", source_at: new Date().toISOString(),
  received_at: new Date().toISOString(), expires_at: new Date(Date.now() + (expired ? -1000 : 15_000)).toISOString(),
  delayed: false, trade_id: null,
});

beforeEach(async () => {
  await activateLanguage("en");
  balance = "1000.00000000"; quoteCount = 0;
  server.use(
    signedIn(),
    http.get(prefix + "/capabilities", () => HttpResponse.json(envelope({ enabled: true, simulated: true }))),
    http.get(prefix + "/wallet", () => HttpResponse.json(envelope({ balance, currency: "credits" }))),
    http.post(prefix + "/quotes", () => HttpResponse.json(envelope(quote()))),
  );
});
afterEach(async () => { vi.useRealTimers(); await act(async () => { await activateLanguage("en"); }); });

async function choose(method: string, cardType?: string) {
  const labels: Record<string, string> = { credits: "TradingMaster funds", card: "Payment card", paypal: "PayPal" };
  await userEvent.click(await screen.findByRole("radio", { name: labels[method] }));
  if (cardType) await userEvent.click(screen.getByRole("radio", { name: cardType === "credit" ? "Credit card" : "Debit card" }));
  if (method !== "credits") await screen.findByText("Available simulated funds: 10000.00 USD");
}

async function preview() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Preview purchase" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "Preview purchase" }));
  return screen.findByRole("button", { name: "Confirm purchase" });
}

describe("checkout payments", () => {
  it("preserves full-precision request amounts while formatting the order summary", async () => {
    let budget: unknown;
    server.use(http.post(prefix + "/quotes", async ({ request }) => {
      budget = (await request.json() as { budget: string }).budget;
      return HttpResponse.json(envelope({ ...quote(), amount: "100.12345678", quantity: "0.00012345" }));
    }));
    renderApp(<CheckoutForm ticker="BTC/USD" exchange="kraken" initialBudget="100.12345678" />);
    expect(await screen.findByText("Your exact quantity is calculated from the live quote.")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Order summary" })).toHaveTextContent("100.12");
    await preview();
    expect(budget).toBe("100.12345678");
    expect(screen.getByRole("complementary", { name: "Order summary" })).toHaveTextContent("0.00012345");
    expect(screen.getByText("100.12 credits")).toBeInTheDocument();
  });

  it.each([["card", "debit"], ["card", "credit"], ["paypal", undefined]])("buys with %s %s and preserves wallet funds", async (method, cardType) => {
    let submitted: unknown;
    server.use(http.post(prefix + "/trades", async ({ request }) => {
      submitted = await request.json();
      expect(request.headers.get("Idempotency-Key")).toBeTruthy();
      return HttpResponse.json(envelope({ wallet: { balance }, trade: { id: "bought" } }));
    }));
    renderApp(<CheckoutPage />, { route: "/checkout?ticker=BTC%2FUSD&exchange=kraken" });
    await choose(method!, cardType);
    await userEvent.click(await preview());
    expect(await screen.findByText("Purchase completed.")).toBeInTheDocument();
    expect(submitted).toEqual({ quote_id: "quote-1", payment_method: method, ...(cardType ? { card_type: cardType } : {}) });
    expect(screen.getByText("Simulated TradingMaster balance: 1000.00 credits")).toBeInTheDocument();
    expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute("content", "noindex, nofollow");
  });

  it.each([
    ["Insufficient credits", "Insufficient TradingMaster funds. Add funds or choose another payment method."],
    ["Insufficient simulated payment funds", "Payment declined: insufficient simulated funds."],
    ["Insufficient available credit", "Payment declined: insufficient available credit."],
    ["Payment transaction limit exceeded", "Payment declined: per-transaction limit exceeded."],
  ])("explains a decline: %s", async (detail, translated) => {
    server.use(http.post(prefix + "/trades", () => HttpResponse.json({ detail }, { status: 409 })));
    renderApp(<CheckoutForm ticker="BTC/USD" exchange="kraken" />);
    await userEvent.click(await preview());
    expect(await screen.findByText(translated)).toBeInTheDocument();
  });

  it("requires a fresh quote and reconfirmation after changing payment selection", async () => {
    const submitted: unknown[] = [];
    server.use(http.post(prefix + "/trades", async ({ request }) => {
      submitted.push(await request.json()); return HttpResponse.json(envelope({ trade: { id: "bought" } }));
    }));
    renderApp(<CheckoutForm ticker="BTC/USD" exchange="kraken" />);
    await preview();
    expect(screen.queryByRole("group", { name: "Payment method" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await choose("card", "credit");
    await userEvent.click(await preview());
    await screen.findByText("Purchase completed.");
    expect(quoteCount).toBe(2);
    expect(submitted).toEqual([{ quote_id: "quote-2", payment_method: "card", card_type: "credit" }]);
  });

  it("refreshes expired quotes and requires another confirmation", async () => {
    let requests = 0;
    server.use(http.post(prefix + "/quotes", () => HttpResponse.json(envelope(quote(++requests === 1)))));
    renderApp(<CheckoutForm ticker="BTC/USD" exchange="kraken" />);
    expect(await preview()).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Refresh quote" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm purchase" })).toBeEnabled());
    expect(quoteCount).toBe(2);
    expect(screen.queryByText("Purchase completed.")).not.toBeInTheDocument();
  });

  it("submits a purchase only once on a double click", async () => {
    let count = 0;
    server.use(http.post(prefix + "/trades", async () => {
      count++; await delay(80); return HttpResponse.json(envelope({ trade: { id: "bought" } }));
    }));
    renderApp(<CheckoutForm ticker="BTC/USD" exchange="kraken" />);
    await userEvent.dblClick(await preview());
    await screen.findByText("Purchase completed.");
    expect(count).toBe(1);
  });

  it("links market purchases to localized checkout", async () => {
    await activateLanguage("pl");
    renderApp(<PurchasePanel ticker="PKN.WA/USD" exchange="yahoo" />);
    expect(await screen.findByRole("link", { name: "Kup aktywa" })).toHaveAttribute("href", "/pl/checkout?ticker=PKN.WA%2FUSD&exchange=yahoo&budget=100");
  });

  it("translates Polish checkout and payment declines", async () => {
    await activateLanguage("pl");
    server.use(http.post(prefix + "/trades", () => HttpResponse.json({ detail: "Insufficient available credit" }, { status: 409 })));
    renderApp(<CheckoutPage />, { route: "/pl/checkout?ticker=BTC%2FUSD&exchange=kraken" });
    expect(await screen.findByRole("heading", { name: "Zakup" })).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("radio", { name: "Karta płatnicza" }));
    await userEvent.click(screen.getByRole("radio", { name: "Karta kredytowa" }));
    await screen.findByText("Dostępne symulowane środki: 10000.00 USD");
    await userEvent.click(screen.getByRole("button", { name: "Podgląd zakupu" }));
    await userEvent.click(await screen.findByRole("button", { name: "Potwierdź zakup" }));
    expect(await screen.findByText("Płatność odrzucona: za mało dostępnego kredytu.")).toBeInTheDocument();
  });
});

describe("funding", () => {
  it("reviews a deposit before charging and allows changing the selection", async () => {
    let charged = false;
    server.use(http.post(prefix + "/wallet/top-ups", () => { charged = true; return HttpResponse.json(envelope({ balance })); }));
    renderApp(<WalletPage />);
    await choose("paypal");
    await userEvent.click(screen.getByRole("button", { name: "Review deposit" }));
    expect(charged).toBe(false);
    expect(screen.queryByRole("group", { name: "Payment method" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm simulated deposit" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await choose("card", "credit");
    expect(charged).toBe(false);
  });

  it.each([["card", "debit"], ["card", "credit"], ["paypal", undefined]])("adds simulated funds using %s %s", async (method, cardType) => {
    let submitted: unknown;
    server.use(http.post(prefix + "/wallet/top-ups", async ({ request }) => {
      submitted = await request.json(); balance = "1100.00000000";
      expect(request.headers.get("X-Requested-With")).toBeTruthy();
      expect(request.headers.get("Idempotency-Key")).toBeTruthy();
      return HttpResponse.json(envelope({ balance }));
    }));
    renderApp(<WalletPage />);
    await choose(method!, cardType);
    expect(screen.queryByRole("radio", { name: "TradingMaster funds" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Review deposit" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm simulated deposit" }));
    expect(await screen.findByText("Simulated payment approved. Funds added.")).toBeInTheDocument();
    await screen.findByText("Simulated TradingMaster balance: 1100.00 credits");
    expect(submitted).toEqual({ amount: "100", payment_method: method, ...(cardType ? { card_type: cardType } : {}) });
    expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute("content", "noindex, nofollow");
  });

  it("retains funding idempotency on an uncertain retry and prevents duplicate submission", async () => {
    const keys: string[] = [];
    server.use(http.post(prefix + "/wallet/top-ups", async ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key")!);
      await delay(50);
      return keys.length === 1 ? HttpResponse.error() : HttpResponse.json(envelope({ balance: "1100.00000000" }));
    }));
    renderApp(<WalletPage />);
    await choose("paypal");
    await userEvent.click(screen.getByRole("button", { name: "Review deposit" }));
    const confirm = screen.getByRole("button", { name: "Confirm simulated deposit" });
    await userEvent.dblClick(confirm);
    await screen.findByText("Failed to fetch");
    await waitFor(() => expect(confirm).toBeEnabled());
    await userEvent.click(confirm);
    await screen.findByText("Simulated payment approved. Funds added.");
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it("shows a funding decline without changing the balance", async () => {
    server.use(http.post(prefix + "/wallet/top-ups", () => HttpResponse.json({ detail: "Payment transaction limit exceeded" }, { status: 409 })));
    renderApp(<WalletPage />);
    await choose("paypal");
    await userEvent.click(screen.getByRole("button", { name: "Review deposit" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm simulated deposit" }));
    expect(await screen.findByText("Payment declined: per-transaction limit exceeded.")).toBeInTheDocument();
    expect(screen.getByText("Simulated TradingMaster balance: 1000.00 credits")).toBeInTheDocument();
  });

  it.each([<WalletPage />, <CheckoutPage />])("keeps private forms hidden while signed out", async (page) => {
    server.use(http.get("/api/v1/users/me", () => HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })));
    renderApp(page);
    await screen.findByRole("link", { name: "Sign in to trade" });
    expect(screen.queryByRole("group", { name: "Payment method" })).not.toBeInTheDocument();
    expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute("content", "noindex, nofollow");
  });
});

function SessionButtons() {
  const { login, logout } = useAuth();
  return <><button onClick={() => void login("trader@example.com", "unused")}>Test login</button>
    <button onClick={() => void logout()}>Test logout</button></>;
}

function shell() {
  return renderApp(<Routes><Route element={<AppShell />}><Route index element={<SessionButtons />} /></Route></Routes>);
}

describe("header balance", () => {
  it.each(["purchase", "deposit", "sale"])("refreshes after a %s", async (action) => {
    const holding = { id: "holding", ticker: "BTC/USD", exchange: "kraken", quantity: "1.00000000",
      cost: "100.00000000", opened_at: new Date().toISOString(), status: "open",
      valuation: { bid: "99", ask: "100", sell_value: "99", unrealized_pnl: "-1", spread: "1", spread_percent: "1" } };
    server.use(
      http.post(prefix + "/trades", () => {
        balance = "900.00000000"; return HttpResponse.json(envelope({ trade: holding, wallet: { balance } }));
      }),
      http.post(prefix + "/wallet/top-ups", () => {
        balance = "1100.00000000"; return HttpResponse.json(envelope({ balance }));
      }),
      http.get(prefix + "/trades", () => HttpResponse.json(envelope({ items: [holding], total: 1, limit: 10 }))),
      http.post(prefix + "/trades/:id/sell", () => {
        balance = "1099.00000000"; return HttpResponse.json(envelope({ trade: { ...holding, status: "closed" }, wallet: { balance } }));
      }),
      http.post(prefix + "/quotes", () => HttpResponse.json(envelope(action === "sale"
        ? { ...quote(), side: "sell", trade_id: holding.id } : quote()))),
    );
    const page = action === "purchase" ? <CheckoutForm ticker="BTC/USD" exchange="kraken" />
      : action === "deposit" ? <WalletPage /> : <TradesPage />;
    renderApp(<Routes><Route element={<AppShell />}><Route index element={page} /></Route></Routes>);
    await screen.findByText("Simulated TradingMaster balance: 1000.00 credits", { selector: "header p" });
    if (action === "purchase") await userEvent.click(await preview());
    else if (action === "deposit") {
      await choose("paypal");
      await userEvent.click(screen.getByRole("button", { name: "Review deposit" }));
      await userEvent.click(screen.getByRole("button", { name: "Confirm simulated deposit" }));
    } else {
      await userEvent.click(await screen.findByRole("button", { name: "Sell entire trade" }));
      await userEvent.click(await screen.findByRole("button", { name: "Confirm full sale" }));
    }
    const expected = action === "purchase" ? "900.00" : action === "deposit" ? "1100.00" : "1099.00";
    expect(await screen.findByText(`Simulated TradingMaster balance: ${expected} credits`, { selector: "header p" })).toBeInTheDocument();
  });

  it("appears after login, clears on logout, and isolates the next account", async () => {
    let loggedIn = false;
    let second = false;
    server.use(
      http.get("/api/v1/users/me", () => loggedIn ? HttpResponse.json(second ? { ...USER, id: "second", email: "second@example.com" } : USER)
        : HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })),
      http.post("/api/v1/auth/cookie/login", () => { loggedIn = true; return new HttpResponse(null, { status: 204 }); }),
      http.post("/api/v1/auth/cookie/logout", () => { loggedIn = false; return new HttpResponse(null, { status: 204 }); }),
    );
    shell();
    await screen.findByRole("link", { name: "Sign in" });
    expect(screen.queryByText(/Simulated TradingMaster balance:/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Test login" }));
    expect(await screen.findByText("Simulated TradingMaster balance: 1000.00 credits")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add funds" })).toHaveAttribute("href", "/wallet");
    await userEvent.click(screen.getByRole("button", { name: "Test logout" }));
    await screen.findByRole("link", { name: "Sign in" });
    expect(screen.queryByText(/1000.00 credits/)).not.toBeInTheDocument();
    second = true; balance = "77.00000000";
    await userEvent.click(screen.getByRole("button", { name: "Test login" }));
    expect(await screen.findByText("Simulated TradingMaster balance: 77.00 credits")).toBeInTheDocument();
    expect(screen.queryByText(/1000.00 credits/)).not.toBeInTheDocument();
  });

  it("refreshes when the window regains focus", async () => {
    shell();
    await screen.findByText("Simulated TradingMaster balance: 1000.00 credits");
    balance = "950.00000000";
    act(() => window.dispatchEvent(new Event("visibilitychange")));
    expect(await screen.findByText("Simulated TradingMaster balance: 950.00 credits")).toBeInTheDocument();
  });

  it("refreshes every 30 seconds", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    shell();
    await screen.findByText("Simulated TradingMaster balance: 1000.00 credits");
    balance = "900.00000000";
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(await screen.findByText("Simulated TradingMaster balance: 900.00 credits")).toBeInTheDocument();
  });

  it("shows an error when balance loading fails", async () => {
    server.use(http.get(prefix + "/wallet", () => HttpResponse.error()));
    shell();
    expect(await screen.findByText("Simulated TradingMaster balance: Balance unavailable")).toBeInTheDocument();
  });
});
