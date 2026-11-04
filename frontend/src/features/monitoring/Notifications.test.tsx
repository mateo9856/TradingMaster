import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/features/auth/auth";
import { USER, envelope, signedIn } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";
import { Notifications } from "./Notifications";
import type { Signal } from "./api";
import { parseUtc } from "@/shared/format";

const root = "/api/v1/monitoring";
let items: Signal[];
let feedCalls: number;
let readCalls: number;
function signal(n = 1, overrides: Partial<Signal> = {}): Signal {
  return { id: `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`, kind: "forecast", direction: "up",
    created_at: "2026-11-04T10:01:00", read_at: null,
    payload: { exchange: "kraken", ticker: "BTC/USD", trade_id: null, change_percent: "12", threshold_percent: "10",
      data_at: "2026-11-04T10:00:00", forecast: { status: "ready", target_date: "2099-01-01" } }, ...overrides };
}
function Harness() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const { logout, login } = useAuth();
  return <><Notifications />
    <button onClick={() => void client.invalidateQueries({ queryKey: ["monitoring", USER.id, "notification-feed"] })}>Next check</button>
    <button onClick={() => navigate("/markets")}>Other page</button>
    <button onClick={() => void logout()}>Log out</button>
    <button onClick={() => void login("other@example.com", "unused")}>Log in</button>
    <output aria-label="Location">{location.pathname}{location.search}</output>
  </>;
}
async function start() {
  renderApp(<Harness />);
  await waitFor(() => expect(feedCalls).toBeGreaterThan(0));
}
async function check() { await userEvent.click(screen.getByRole("button", { name: "Next check" })); }
function bell() { return screen.getByRole("button", { name: /Notifications/ }); }

beforeEach(() => {
  items = []; feedCalls = 0; readCalls = 0;
  server.use(
    signedIn(),
    http.post("/api/v1/auth/cookie/logout", () => new HttpResponse(null, { status: 204 })),
    http.post("/api/v1/auth/cookie/login", () => new HttpResponse(null, { status: 204 })),
    http.get(root + "/alerts", ({ request }) => {
      const url = new URL(request.url);
      const after = url.searchParams.get("after");
      let rows = [...items];
      if (after) {
        feedCalls++;
        const stamp = parseUtc(after).getTime();
        const id = url.searchParams.get("after_id");
        rows = rows.filter((row) => parseUtc(row.created_at).getTime() > stamp
          || (parseUtc(row.created_at).getTime() === stamp && (!id || row.id > id)));
        rows.sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
      } else rows.sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id));
      return HttpResponse.json(envelope({ items: rows.slice(0, Number(url.searchParams.get("limit") ?? 20)),
        unread_count: items.filter((row) => !row.read_at).length, checked_at: "2026-11-04T10:00:00" }));
    }),
    http.patch(root + "/alerts/:id/read", ({ params, request }) => {
      readCalls++;
      expect(request.headers.get("X-Requested-With")).toBeTruthy();
      const item = items.find((row) => row.id === params.id);
      if (item) item.read_at = "2026-11-04T10:02:00";
      return HttpResponse.json(envelope(null));
    }),
  );
});

describe("notification bell and popups", () => {
  it("hides notifications when signed out", async () => {
    server.use(http.get("/api/v1/users/me", () => HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })));
    renderApp(<Harness />);
    await screen.findByRole("button", { name: "Log in" });
    expect(screen.queryByRole("button", { name: /Notifications/ })).not.toBeInTheDocument();
    expect(feedCalls).toBe(0);
  });

  it("shows existing unread history in the bell without replaying old popups", async () => {
    items = [signal()];
    await start();
    expect(bell()).toHaveAccessibleName("Notifications — unread: 1");
    expect(screen.queryByRole("region", { name: "New notifications" })).not.toBeInTheDocument();
    await userEvent.click(bell());
    const panel = screen.getByRole("region", { name: "Recent notifications" });
    expect(within(panel).getByRole("button", { name: "Close notifications" })).toHaveFocus();
    expect(within(panel).getByText("Potential buying opportunity: BTC/USD")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "View all notifications" })).toHaveAttribute("href", "/monitoring?tab=alerts");
    expect(readCalls).toBe(0);
    await userEvent.keyboard("{Escape}");
    expect(bell()).toHaveAttribute("aria-expanded", "false");
    expect(bell()).toHaveFocus();
    await userEvent.click(bell());
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("region", { name: "Recent notifications" })).not.toBeInTheDocument();
  });

  it("shows a new buying opportunity across pages and does not repeat a dismissed popup", async () => {
    await start();
    items.push(signal()); await check();
    const popups = await screen.findByRole("region", { name: "New notifications" });
    expect(within(popups).getByText("Potential buying opportunity: BTC/USD")).toBeInTheDocument();
    await waitFor(() => expect(bell()).toHaveAccessibleName("Notifications — unread: 1"));
    expect(within(popups).getByText(/Estimated change \+12.00%/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Other page" }));
    expect(screen.getByLabelText("Location")).toHaveTextContent("/markets");
    expect(screen.getByRole("region", { name: "New notifications" })).toBeInTheDocument();
    await userEvent.click(within(popups).getByRole("button", { name: /Dismiss:/ }));
    await check();
    expect(screen.queryByRole("region", { name: "New notifications" })).not.toBeInTheDocument();
    expect(readCalls).toBe(0);
  });

  it("opens and marks an older notification read from the bell panel", async () => {
    items = [signal()];
    await start();
    await userEvent.click(bell());
    const panel = screen.getByRole("region", { name: "Recent notifications" });
    await userEvent.click(within(panel).getByRole("button", { name: "View alert" }));
    await waitFor(() => expect(readCalls).toBe(1));
    await waitFor(() => expect(screen.getByLabelText("Location")).toHaveTextContent(`/monitoring?tab=alerts&notification=${items[0].id}`));
    expect(screen.queryByRole("region", { name: "Recent notifications" })).not.toBeInTheDocument();
  });

  it("uses selling wording for a downward holding forecast and price wording for an actual rise", async () => {
    await start();
    const holding = signal(1, { direction: "down" });
    holding.payload = { ...holding.payload, trade_id: "position-1", change_percent: "-12" };
    items.push(holding, signal(2, { kind: "observed" })); await check();
    await screen.findByText("Potential selling opportunity: BTC/USD");
    expect(screen.getByText("Price rise: BTC/USD")).toBeInTheDocument();
    expect(screen.queryByText("Potential buying opportunity: BTC/USD")).not.toBeInTheDocument();
  });

  it("marks a notification read and opens its alert in Monitoring", async () => {
    await start(); items.push(signal()); await check();
    const popups = await screen.findByRole("region", { name: "New notifications" });
    await userEvent.click(within(popups).getByRole("button", { name: "View alert" }));
    await waitFor(() => expect(screen.getByLabelText("Location")).toHaveTextContent(`/monitoring?tab=alerts&notification=${items[0].id}`));
    expect(readCalls).toBe(1);
    expect(bell()).toHaveAccessibleName("Notifications — unread: 0");
    expect(screen.queryByRole("region", { name: "New notifications" })).not.toBeInTheDocument();
  });

  it("retains a popup and unread state when marking it read fails", async () => {
    server.use(http.patch(root + "/alerts/:id/read", () => HttpResponse.json({ detail: "Try later" }, { status: 503 })));
    await start(); items.push(signal()); await check();
    const popups = await screen.findByRole("region", { name: "New notifications" });
    await userEvent.click(within(popups).getByRole("button", { name: "View alert" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try later");
    expect(screen.getByRole("region", { name: "New notifications" })).toBeInTheDocument();
    expect(items[0].read_at).toBeNull();
  });

  it("pages through a burst without flooding the screen", async () => {
    await start();
    for (let i = 1; i <= 120; i++) items.push(signal(i));
    await check();
    const popups = await screen.findByRole("region", { name: "New notifications" });
    await within(popups).findByText("More new notifications: 117");
    expect(within(popups).getAllByRole("button", { name: /Dismiss:/ })).toHaveLength(3);
    expect(feedCalls).toBeGreaterThanOrEqual(3);
    await check();
    expect(within(popups).getByText("More new notifications: 117")).toBeInTheDocument();
  });

  it("keeps read or expired forecasts in history without showing opportunity popups", async () => {
    await start();
    const expired = signal(); expired.payload.forecast!.target_date = "2020-01-01";
    items.push(expired, signal(2, { read_at: "2026-11-04T10:02:00" })); await check();
    expect(screen.queryByRole("region", { name: "New notifications" })).not.toBeInTheDocument();
  });

  it("clears visible notifications on logout and isolates another account", async () => {
    await start(); items.push(signal()); await check();
    await screen.findByRole("region", { name: "New notifications" });
    await userEvent.click(screen.getByRole("button", { name: "Log out" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Notifications/ })).not.toBeInTheDocument());
    expect(screen.queryByRole("region", { name: "New notifications" })).not.toBeInTheDocument();
    items = [];
    server.use(signedIn({ ...USER, id: "22222222-2222-2222-2222-222222222222", email: "other@example.com" }));
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));
    await screen.findByRole("button", { name: "Notifications — unread: 0" });
    await userEvent.click(bell());
    expect(screen.getByText("No alerts yet.")).toBeInTheDocument();
    expect(screen.queryByText("Potential buying opportunity: BTC/USD")).not.toBeInTheDocument();
  });
});
