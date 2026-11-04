import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";

import { MonitoringPage } from "./MonitoringPage";
import { MonitoringSettings } from "./MonitoringSettings";
import { WatchButton } from "./WatchButton";
import { envelope, signedIn } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

const root = "/api/v1/monitoring";
const settings = { enabled: false, upward_percent: "10", downward_percent: "10", check_minutes: 60,
  horizon_days: 1, forecasts_enabled: true, next_check_at: null };
const target = { id: "watch-1", exchange: "kraken", ticker: "BTC/USD", trade_id: null,
  reference_price: "100", created_at: "2026-10-31T12:00:00", result: { status: "ready", price: "110",
    change_percent: "10", forecast: { status: "insufficient_history" } } };

// jsdom has no native modal implementation; Chrome checks cover focus trapping.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
});

beforeEach(() => server.use(
  signedIn(),
  http.get("/api/v1/trading/capabilities", () => HttpResponse.json(envelope({ enabled: true, simulated: true }))),
  http.get(root + "/settings", () => HttpResponse.json(envelope(settings))),
  http.get(root + "/watchlist", () => HttpResponse.json(envelope([target]))),
  http.get(root + "/holdings", () => HttpResponse.json(envelope([{ ...target, trade_id: "position-1" }]))),
  http.get(root + "/alerts", () => HttpResponse.json(envelope({ items: [], unread_count: 0 }))),
));

describe("monitoring", () => {
  it("persists independent frequency and 365-day forecast settings", async () => {
    let submitted: unknown;
    server.use(http.put(root + "/settings", async ({ request }) => {
      submitted = await request.json();
      expect(request.headers.get("X-Requested-With")).toBeTruthy();
      return HttpResponse.json(envelope({ ...settings, ...(submitted as object) }));
    }));
    renderApp(<MonitoringSettings />);
    await screen.findByLabelText("Enable monitoring");
    await userEvent.click(screen.getByLabelText("Enable monitoring"));
    await userEvent.clear(screen.getByLabelText("Forecast horizon (days)"));
    await userEvent.type(screen.getByLabelText("Forecast horizon (days)"), "365");
    await userEvent.selectOptions(screen.getByLabelText("Check frequency"), "15");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await screen.findByText("Settings saved");
    expect(submitted).toMatchObject({ enabled: true, check_minutes: 15, horizon_days: 365 });
  });

  it("shows paused monitoring and unavailable forecasts, and opens a specific holding", async () => {
    renderApp(<MonitoringPage />);
    await screen.findByText(/Monitoring is paused/);
    expect(await screen.findByText(/Insufficient history/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Holdings" }));
    await waitFor(() => expect(screen.getByRole("link", { name: "View position" })).toHaveAttribute("href", "/trades?trade=position-1"));
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  });

  it("adds a watch without executing a trade", async () => {
    let watched = false;
    server.use(http.post(root + "/watchlist", async ({ request }) => {
      expect(await request.json()).toEqual({ exchange: "kraken", ticker: "BTC/USD", enable_monitoring: false });
      watched = true;
      return HttpResponse.json(envelope(target));
    }));
    renderApp(<WatchButton exchange="kraken" ticker="BTC/USD" />);
    await screen.findByRole("button", { name: "Watch" });
    await userEvent.click(screen.getByRole("button", { name: "Watch" }));
    await userEvent.click(await screen.findByRole("button", { name: "Watch while paused" }));
    await screen.findByText(/Added to watchlist/);
    expect(watched).toBe(true);
  });

  it("marks an alert read and displays its source timestamp", async () => {
    let read = false;
    server.use(
      http.get(root + "/alerts", () => HttpResponse.json(envelope({ unread_count: read ? 0 : 1, items: [{
        id: "a1", kind: "observed", direction: "up", created_at: "2026-10-31T12:00:00", read_at: read ? "2026-10-31T13:00:00" : null,
        payload: { exchange: "kraken", ticker: "BTC/USD", trade_id: null, change_percent: "10", data_at: "2026-10-31T11:59:00", forecast: null },
      }] }))),
      http.patch(root + "/alerts/a1/read", () => { read = true; return HttpResponse.json(envelope(null)); }),
    );
    renderApp(<MonitoringPage />, { route: "/monitoring?tab=alerts" });
    await screen.findByRole("button", { name: "Mark as read" });
    await userEvent.click(screen.getByRole("button", { name: "Mark as read" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Alerts (0)" })).toBeInTheDocument());
    expect(read).toBe(true);
  });
});

describe("watch activation and monitoring feedback", () => {
  it("enables monitoring atomically with the watch after confirmation", async () => {
    let posted: unknown;
    server.use(http.post(root + "/watchlist", async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json(envelope(target));
    }));
    renderApp(<WatchButton exchange="kraken" ticker="BTC/USD" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Watch" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Watch" }));
    const dialog = await screen.findByRole("dialog", { name: "Start watching this asset?" });
    expect(within(dialog).getByText(/all your watches and holdings/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Watch and enable monitoring" }));
    await screen.findByText("Added to watchlist. Monitoring is enabled.");
    expect(posted).toEqual({ exchange: "kraken", ticker: "BTC/USD", enable_monitoring: true });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("cancels without creating a watch and restores trigger focus", async () => {
    renderApp(<WatchButton exchange="kraken" ticker="BTC/USD" />);
    const trigger = await screen.findByRole("button", { name: "Watch" });
    await waitFor(() => expect(trigger).toBeEnabled());
    await userEvent.click(trigger);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    await userEvent.click(trigger);
    fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.queryByText(/Added to watchlist/)).not.toBeInTheDocument();
  });

  it("adds directly when already enabled", async () => {
    let watched = false;
    server.use(
      http.get(root + "/settings", () => HttpResponse.json(envelope({ ...settings, enabled: true }))),
      http.post(root + "/watchlist", () => { watched = true; return HttpResponse.json(envelope(target)); }),
    );
    renderApp(<WatchButton exchange="kraken" ticker="BTC/USD" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Watch" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Watch" }));
    await screen.findByText("Added to watchlist. Monitoring is enabled.");
    expect(watched).toBe(true);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows a dated saved price and a styled checkout action while paused", async () => {
    server.use(http.get(root + "/watchlist", () => HttpResponse.json(envelope([{ ...target,
      result: { snapshot: { price: "110", data_at: "2026-11-01T12:00:00", interval: "1m" } },
    }]))));
    renderApp(<MonitoringPage />);
    expect(await screen.findByText("Saved candle close: $110")).toBeInTheDocument();
    expect(screen.getByText("Price updates and alerts are paused.")).toBeInTheDocument();
    const checkout = screen.getByRole("link", { name: "Checkout" });
    expect(checkout).toHaveAttribute("href", "/checkout?ticker=BTC%2FUSD&exchange=kraken");
    expect(checkout).toHaveClass("bg-primary", "h-9");
    expect(checkout).not.toHaveClass("underline");
  });

  it("enables from the panel using only the toggle field", async () => {
    let enabled = false;
    server.use(
      http.get(root + "/settings", () => HttpResponse.json(envelope({ ...settings, enabled }))),
      http.get(root + "/watchlist", () => HttpResponse.json(envelope([{ ...target, result: {} }]))),
      http.patch(root + "/settings", async ({ request }) => {
        expect(await request.json()).toEqual({ enabled: true });
        enabled = true;
        return HttpResponse.json(envelope({ ...settings, enabled }));
      }),
    );
    renderApp(<MonitoringPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Enable monitoring" }));
    await screen.findByText("Status: Waiting for first check");
    expect(screen.queryByText(/Monitoring is paused/)).not.toBeInTheDocument();
    expect(screen.getByText(/No saved price yet/)).toBeInTheDocument();
    expect(screen.queryByText(/Reference price: —/)).not.toBeInTheDocument();
  });

  it("does not interpret loading settings as paused", async () => {
    server.use(http.get(root + "/settings", async () => {
      await new Promise((resolve) => setTimeout(resolve, 120));
      return HttpResponse.json(envelope({ ...settings, enabled: true, next_check_at: "2020-01-01T00:00:00" }));
    }));
    renderApp(<MonitoringPage />);
    await screen.findByText(/BTC\/USD · kraken/);
    expect(screen.queryByText("Status: Paused")).not.toBeInTheDocument();
    await screen.findByText(/Monitoring checks are delayed/);
  });

  it("keeps the dialog open on save failure and permits retry", async () => {
    let calls = 0;
    server.use(http.post(root + "/watchlist", () => ++calls === 1
      ? HttpResponse.json({ detail: "Save failed" }, { status: 503 }) : HttpResponse.json(envelope(target))));
    renderApp(<WatchButton exchange="kraken" ticker="BTC/USD" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Watch" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Watch" }));
    await userEvent.click(await screen.findByRole("button", { name: "Watch while paused" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Save failed");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Watch while paused" }));
    await screen.findByText("Added to watchlist. Monitoring remains paused.");
    expect(calls).toBe(2);
  });
});

it("identifies disabled forecasting independently of monitoring activity", async () => {
  server.use(http.get(root + "/settings", () => HttpResponse.json(envelope({ ...settings, forecasts_enabled: false }))));
  renderApp(<MonitoringPage />);
  expect(await screen.findByText("Experimental forecast: Disabled")).toBeInTheDocument();
});
