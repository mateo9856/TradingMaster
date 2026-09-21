import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { HistoryPage } from "./HistoryPage";
import { historyCandle, envelope, signedIn } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

async function search() {
  await userEvent.click(await screen.findByRole("button", { name: "Search" }));
}

describe("searching archived candles", () => {
  it("lists the rows with their source market", async () => {
    renderApp(<HistoryPage />);

    await search();

    expect(await screen.findByText("2026-09-19 12:00:00")).toBeInTheDocument();
    // Scoped to the table — "binance" also appears in the exchange filter.
    const table = within(screen.getByRole("table"));
    expect(table.getByText("binance")).toBeInTheDocument();
    expect(table.getByText("BTC/USDT")).toBeInTheDocument();
    expect(table.getByText("65,200.00")).toBeInTheDocument();
    expect(screen.getByText(/1 row/)).toBeInTheDocument();
  });

  it("sends the chosen range and filters to the API", async () => {
    let url: URL | null = null;
    server.use(
      http.get("/api/v1/history/*", ({ request }) => {
        url = new URL(request.url);
        return HttpResponse.json(envelope([historyCandle()]));
      }),
    );
    renderApp(<HistoryPage />);

    await userEvent.selectOptions(screen.getByLabelText("Interval"), "1h");
    await search();

    await waitFor(() => expect(url).not.toBeNull());
    expect(url!.pathname).toBe("/api/v1/history/BTC%2FUSD");
    expect(url!.searchParams.get("interval")).toBe("1h");
    expect(url!.searchParams.get("date_from")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("explains an empty range rather than showing an error", async () => {
    server.use(
      http.get("/api/v1/history/*", () =>
        HttpResponse.json({ detail: "No history found" }, { status: 404 }),
      ),
    );
    renderApp(<HistoryPage />);

    await search();

    expect(await screen.findByText(/No archived candles for that range/i)).toBeInTheDocument();
  });

  it("shows the API's message for an unsupported market", async () => {
    server.use(
      http.get("/api/v1/history/*", () =>
        HttpResponse.json({ detail: "Unsupported quote currency in 'ETH/BTC'" }, { status: 422 }),
      ),
    );
    renderApp(<HistoryPage />);

    await userEvent.clear(screen.getByLabelText("Market"));
    await userEvent.type(screen.getByLabelText("Market"), "ETH/BTC");
    await search();

    expect(await screen.findByText(/Unsupported market/i)).toBeInTheDocument();
    expect(screen.getByText(/Unsupported quote currency/)).toBeInTheDocument();
  });
});

describe("archive trigger", () => {
  it("is disabled with an explanation when signed out", async () => {
    renderApp(<HistoryPage />);

    expect(await screen.findByRole("button", { name: "Run archive" })).toBeDisabled();
    expect(screen.getByText(/Sign in to run the archive/i)).toBeInTheDocument();
  });

  it("starts the job for a signed-in user and reports the accepted message", async () => {
    server.use(
      signedIn(),
      http.post("/api/v1/history/archive/:date", ({ params }) =>
        HttpResponse.json(
          { status: "accepted", message: `Archive job started for ${params.date}`, data: null },
          { status: 202 },
        ),
      ),
    );
    renderApp(<HistoryPage />);

    const button = await screen.findByRole("button", { name: "Run archive" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);

    expect(await screen.findByText(/Archive started/i)).toBeInTheDocument();
    expect(screen.getByText(/Archive job started for \d{4}-\d{2}-\d{2}/)).toBeInTheDocument();
  });

  it("reports a rejected trigger", async () => {
    server.use(
      signedIn(),
      http.post("/api/v1/history/archive/:date", () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 }),
      ),
    );
    renderApp(<HistoryPage />);

    const button = await screen.findByRole("button", { name: "Run archive" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);

    expect(await screen.findByText(/Could not start the archive/i)).toBeInTheDocument();
  });
});
