import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { AppShell } from "./AppShell";
import { STORAGE_KEY } from "@/lib/currency";
import { USER, signedIn } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

function renderShell() {
  return renderApp(
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<p>page</p>} />
      </Route>
    </Routes>,
  );
}

const picker = () => screen.getByLabelText("Currency") as HTMLSelectElement;

describe("currency picker", () => {
  const originalTz = process.env.TZ;
  afterEach(() => {
    process.env.TZ = originalTz;
  });

  it("opens in PLN on a machine in Poland", async () => {
    process.env.TZ = "Europe/Warsaw";
    renderShell();

    await waitFor(() => expect(picker()).toHaveValue("PLN"));
  });

  it("opens in USD where nothing points elsewhere", async () => {
    renderShell();

    await waitFor(() => expect(picker().options.length).toBeGreaterThan(1));
    expect(picker()).toHaveValue("USD");
  });

  it("remembers a choice in this browser", async () => {
    process.env.TZ = "Europe/Warsaw";
    renderShell();
    await waitFor(() => expect(picker()).toHaveValue("PLN"));

    await userEvent.selectOptions(picker(), "NOK");

    expect(picker()).toHaveValue("NOK");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("NOK");
  });

  it("opens in the signed-in user's saved currency and saves a new choice to the profile", async () => {
    let patched: unknown = null;
    server.use(
      signedIn({ ...USER, preferred_currency: "EUR" }),
      http.patch("/api/v1/users/me", async ({ request }) => {
        patched = await request.json();
        return HttpResponse.json({ ...USER, preferred_currency: "PLN" });
      }),
    );
    renderShell();
    await waitFor(() => expect(picker()).toHaveValue("EUR"));

    await userEvent.selectOptions(picker(), "PLN");

    await waitFor(() => expect(patched).toEqual({ preferred_currency: "PLN" }));
    expect(picker()).toHaveValue("PLN");
  });

  it("offers USD only when the currency list can't be loaded", async () => {
    server.use(http.get("/api/v1/currencies", () => HttpResponse.error()));
    process.env.TZ = "Europe/Warsaw";
    renderShell();

    await waitFor(() => expect(picker()).toHaveValue("USD"));
    expect(picker().options).toHaveLength(1);
  });
});
