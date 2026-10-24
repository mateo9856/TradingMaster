import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { PurchasePanel } from "./PurchasePanel";
import { envelope, signedIn } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

const capabilities = "/api/v1/trading/capabilities";

function enableTrading() {
  server.use(http.get(capabilities, () => HttpResponse.json(envelope({ enabled: true, simulated: true }))));
}

describe("chart purchase action", () => {
  it("shows a primary Buy action for the selected market after sign-in", async () => {
    enableTrading();
    server.use(signedIn());
    renderApp(<PurchasePanel ticker="BTC/USD" exchange="kraken" />);
    const action = await screen.findByRole("link", { name: "Buy assets" });
    expect(action).toHaveAttribute("href", "/checkout?ticker=BTC%2FUSD&exchange=kraken&budget=100");
    expect(action).toHaveClass("bg-primary");
    expect(screen.getByText("Simulated trading · no real payments or holdings")).toBeInTheDocument();
  });

  it("prompts signed-out users to sign in", async () => {
    enableTrading();
    renderApp(<PurchasePanel ticker="BTC/USD" exchange="kraken" />);
    expect(await screen.findByRole("link", { name: "Sign in to trade" })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("link", { name: "Buy assets" })).not.toBeInTheDocument();
  });

  it("keeps Buy visible with an explanation when trading is disabled", async () => {
    server.use(signedIn());
    renderApp(<PurchasePanel ticker="BTC/USD" exchange="kraken" />);
    expect(await screen.findByText("Simulated trading is disabled.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Buy assets" })).toBeDisabled();
  });

  it("shows a disabled Buy action while capabilities are loading", async () => {
    server.use(signedIn(), http.get(capabilities, async () => {
      await delay(100);
      return HttpResponse.json(envelope({ enabled: true, simulated: true }));
    }));
    renderApp(<PurchasePanel ticker="BTC/USD" exchange="kraken" />);
    expect(screen.getByRole("button", { name: "Buy assets" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
    expect(await screen.findByRole("link", { name: "Buy assets" })).toBeInTheDocument();
  });

  it("shows capabilities errors and allows recovery without reloading", async () => {
    let requests = 0;
    server.use(signedIn(), http.get(capabilities, () => ++requests === 1
      ? HttpResponse.error() : HttpResponse.json(envelope({ enabled: true, simulated: true }))));
    renderApp(<PurchasePanel ticker="BTC/USD" exchange="kraken" />);
    expect(await screen.findByText("Trading is temporarily unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Buy assets" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Buy assets" })).toBeInTheDocument());
    expect(requests).toBe(2);
  });
});
