import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import i18n, { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";
import { installFakeWebSocket } from "@/test/fake-websocket";
import { renderApp } from "@/test/render";
import { envelope, signedIn } from "@/test/handlers";
import { server } from "@/test/server";

vi.mock("@/components/CandleChart", () => ({ CandleChart: () => <div data-testid="candle-chart" /> }));

function Where() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}</output>;
}

function renderAt(route: string) {
  installFakeWebSocket();
  return renderApp(
    <>
      <App />
      <Where />
    </>,
    { route },
  );
}

const where = () => screen.getByTestId("location").textContent;

afterEach(async () => {
  vi.unstubAllGlobals();
  process.env.TZ = "UTC";
  await i18n.changeLanguage("en");
});

describe("market pages", () => {
  it.each([
    ["/markets/bitcoin-btc", "BTC/USD", "kraken"],
    ["/markets/orlen-pkn-wa", "PKN.WA/USD", "yahoo"],
  ])("offers buying beside the chart on %s and opens checkout for the selected exchange", async (route, ticker, exchange) => {
    server.use(signedIn(),
      http.get("/api/v1/trading/capabilities", () => HttpResponse.json(envelope({ enabled: true, simulated: true }))),
      http.get("/api/v1/trading/wallet", () => HttpResponse.json(envelope({ balance: "10000.00000000", currency: "credits" }))),
    );
    renderAt(route);
    await screen.findByTestId("candle-chart", {}, { timeout: 5000 });
    await userEvent.selectOptions(screen.getByLabelText("Exchange"), exchange);
    const chart = screen.getByTestId("candle-chart").parentElement!.parentElement!;
    const buy = within(chart).getByRole("link", { name: "Buy assets" });
    expect(screen.getAllByRole("link", { name: "Buy assets" })).toHaveLength(1);
    const target = new URL(buy.getAttribute("href")!, window.location.origin);
    expect(target.searchParams.get("ticker")).toBe(ticker);
    expect(target.searchParams.get("exchange")).toBe(exchange);
    expect(target.searchParams.get("budget")).toBe("100");
    await userEvent.click(buy);
    expect(await screen.findByRole("heading", { name: "Checkout" })).toBeInTheDocument();
    expect(where()).toBe("/checkout");
  });

  it("updates the Buy action when another market is selected", async () => {
    server.use(signedIn(),
      http.get("/api/v1/trading/capabilities", () => HttpResponse.json(envelope({ enabled: true, simulated: true }))),
      http.get("/api/v1/trading/wallet", () => HttpResponse.json(envelope({ balance: "10000.00000000", currency: "credits" }))),
    );
    renderAt("/markets/bitcoin-btc");
    await screen.findByRole("link", { name: "Buy assets" });
    await userEvent.selectOptions(screen.getByLabelText("Market"), "PKN.WA/USD");
    await waitFor(() => expect(screen.getByRole("link", { name: "Buy assets" })).toHaveAttribute("href", "/checkout?ticker=PKN.WA%2FUSD&exchange=yahoo&budget=100"));
  });

  it("say what the instrument is, with one h1", async () => {
    renderAt("/markets/bitcoin-btc");

    const heading = await screen.findByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("Bitcoin (BTC)");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByText("Bitcoin (BTC) is a cryptocurrency. Category: Digital currency.")).toBeInTheDocument();
    expect(screen.getByText("Digital currency")).toBeInTheDocument();
  });

  it("name stocks and where they are listed", async () => {
    renderAt("/markets/orlen-pkn-wa");

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("ORLEN S.A. (PKN.WA)");
    expect(screen.getByText("Warsaw Stock Exchange (GPW)")).toBeInTheDocument();
  });

  it("set the page title from the API", async () => {
    renderAt("/markets/bitcoin-btc");

    await waitFor(() => expect(document.title).toBe("Bitcoin (BTC) price today, live chart | TradingMaster"));
    const canonical = document.head.querySelector('link[rel="canonical"]');
    expect(canonical?.getAttribute("href")).toBe(`${window.location.origin}/markets/bitcoin-btc`);
    expect(document.head.querySelectorAll('link[rel="alternate"][hreflang]')).toHaveLength(8);
  });

  it("move to the chosen market's own URL", async () => {
    renderAt("/markets/bitcoin-btc");

    await userEvent.selectOptions(await screen.findByLabelText("Market"), "PKN.WA/USD");

    await waitFor(() => expect(where()).toBe("/markets/orlen-pkn-wa"));
  });

  it("explain an address that names no market", async () => {
    renderAt("/markets/no-such-thing");

    expect(await screen.findByText("Market not found")).toBeInTheDocument();
    await waitFor(() =>
      expect(document.head.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe("noindex, nofollow"),
    );
  });
});

describe("languages", () => {
  it("serve Polish at /pl", async () => {
    renderAt("/pl/markets");

    expect(await screen.findByRole("heading", { level: 1, name: "Wszystkie rynki" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("pl");
    expect(screen.getByRole("link", { name: "Rynki" })).toHaveAttribute("href", "/pl/markets");
  });

  it("redirect /en/… to the unprefixed English URL", async () => {
    renderAt("/en/markets");

    await waitFor(() => expect(where()).toBe("/markets"));
  });

  it("treat an unknown language prefix as a missing page", async () => {
    renderAt("/xx/markets");

    expect(await screen.findByText("Page not found.")).toBeInTheDocument();
  });

  it("send a first-time visitor in Poland to Polish", async () => {
    process.env.TZ = "Europe/Warsaw";
    renderAt("/markets");

    await waitFor(() => expect(where()).toBe("/pl/markets"));
  });

  it("respect a remembered choice of English", async () => {
    process.env.TZ = "Europe/Warsaw";
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    renderAt("/markets");

    expect(await screen.findByRole("heading", { level: 1, name: "All markets" })).toBeInTheDocument();
    expect(where()).toBe("/markets");
  });

  it("switch language without leaving the page, and remember it", async () => {
    renderAt("/markets");
    await screen.findByRole("heading", { level: 1, name: "All markets" });

    await userEvent.selectOptions(screen.getByLabelText("Language"), "de");

    await waitFor(() => expect(where()).toBe("/de/markets"));
    expect(await screen.findByRole("heading", { level: 1, name: "Alle Märkte" })).toBeInTheDocument();
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("de");
  });
});

describe("markets directory", () => {
  it("lists every market with what it is, linking to its page", async () => {
    renderAt("/markets");

    const table = within(await screen.findByRole("table"));
    expect(table.getByRole("link", { name: "Bitcoin" })).toHaveAttribute("href", "/markets/bitcoin-btc");
    expect(table.getByRole("link", { name: "ORLEN S.A." })).toHaveAttribute("href", "/markets/orlen-pkn-wa");
    expect(screen.getByText("3 markets")).toBeInTheDocument();
  });

  it("searches by name or symbol", async () => {
    renderAt("/markets");
    await screen.findByRole("table");

    await userEvent.type(screen.getByLabelText("Search by name or symbol"), "orlen");
    expect(within(screen.getByRole("table")).getAllByRole("link")).toHaveLength(1);

    await userEvent.clear(screen.getByLabelText("Search by name or symbol"));
    await userEvent.type(screen.getByLabelText("Search by name or symbol"), "eth");
    expect(within(screen.getByRole("table")).getByRole("link")).toHaveTextContent("Ethereum");

    await userEvent.clear(screen.getByLabelText("Search by name or symbol"));
    await userEvent.type(screen.getByLabelText("Search by name or symbol"), "zzz");
    expect(screen.getByText("No market matches “zzz”.")).toBeInTheDocument();
  });

  it("filters by type", async () => {
    renderAt("/markets");
    await screen.findByRole("table");

    await userEvent.selectOptions(screen.getByLabelText("Type"), "stock");

    expect(within(screen.getByRole("table")).getAllByRole("link").map((a) => a.textContent)).toEqual(["ORLEN S.A."]);
  });
});
