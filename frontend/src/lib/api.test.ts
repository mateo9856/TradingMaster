import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { ApiError, NetworkError, api } from "./api";
import { MARKETS, USER, candle, envelope } from "@/test/handlers";
import { server } from "@/test/server";

describe("reading data", () => {
  it("unwraps the ApiResponse envelope", async () => {
    await expect(api.markets()).resolves.toEqual(MARKETS);
  });

  it("URL-encodes the ticker and passes the filters through", async () => {
    let requested: URL | null = null;
    server.use(
      http.get("/api/v1/market/candles/*", ({ request }) => {
        requested = new URL(request.url);
        return HttpResponse.json(envelope([candle()]));
      }),
    );

    await api.candles({ ticker: "BTC/USD", interval: "30s", exchange: "kraken", limit: 10 });

    expect(requested!.pathname).toBe("/api/v1/market/candles/BTC%2FUSD");
    expect(Object.fromEntries(requested!.searchParams)).toEqual({
      interval: "30s",
      exchange: "kraken",
      limit: "10",
    });
  });

  it("leaves optional filters out of the query string", async () => {
    let requested: URL | null = null;
    server.use(
      http.get("/api/v1/market/candles/*", ({ request }) => {
        requested = new URL(request.url);
        return HttpResponse.json(envelope([candle()]));
      }),
    );

    await api.candles({ ticker: "BTC/USD", interval: "1m" });

    expect(requested!.searchParams.has("exchange")).toBe(false);
  });
});

describe("error mapping", () => {
  it("turns 404 into a typed not-found error carrying the API's message", async () => {
    server.use(
      http.get("/api/v1/market/candles/*", () =>
        HttpResponse.json({ detail: "Ticker BTC/USD nie został znaleziony" }, { status: 404 }),
      ),
    );

    const error = await api.candles({ ticker: "BTC/USD", interval: "1m" }).catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.isNotFound).toBe(true);
    expect(error.message).toContain("nie został znaleziony");
  });

  it("flattens FastAPI's validation detail list", async () => {
    server.use(
      http.get("/api/v1/market/candles/*", () =>
        HttpResponse.json(
          { detail: [{ loc: ["path", "ticker"], msg: "Unsupported quote currency in 'ETH/BTC'" }] },
          { status: 422 },
        ),
      ),
    );

    const error = await api.candles({ ticker: "ETH/BTC", interval: "1m" }).catch((e) => e);

    expect(error.isValidation).toBe(true);
    expect(error.message).toBe("ticker: Unsupported quote currency in 'ETH/BTC'");
  });

  it.each([
    [401, "isUnauthorized"],
    [409, "isConflict"],
  ])("flags %i responses", async (status, flag) => {
    server.use(http.get("/api/v1/users/me", () => HttpResponse.json({ detail: "nope" }, { status })));

    const error = await api.me().catch((e) => e);

    expect(error[flag as keyof ApiError]).toBe(true);
  });

  it("reports an unreachable API as a network error", async () => {
    server.use(http.get("/api/v1/market/markets", () => HttpResponse.error()));

    await expect(api.markets()).rejects.toBeInstanceOf(NetworkError);
  });
});

describe("authentication", () => {
  it("logs in through the cookie backend and keeps no token in the page", async () => {
    let contentType: string | null = null;
    let body = "";
    server.use(
      http.post("/api/v1/auth/cookie/login", async ({ request }) => {
        contentType = request.headers.get("content-type");
        body = await request.text();
        // FastAPI Users' cookie login answers with Set-Cookie and no body.
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await expect(api.login("trader@example.com", "supersecret123")).resolves.toBeUndefined();

    expect(contentType).toContain("application/x-www-form-urlencoded");
    expect(body).toContain("username=trader%40example.com");
    expect(localStorage.length).toBe(0);
    expect(Object.keys(sessionStorage)).toHaveLength(0);
  });

  it("sends no Authorization header — the browser carries the cookie", async () => {
    let authorization: string | null = "unset";
    let credentials: RequestCredentials | undefined;
    server.use(
      http.get("/api/v1/users/me", ({ request }) => {
        authorization = request.headers.get("authorization");
        credentials = request.credentials;
        return HttpResponse.json(USER);
      }),
    );

    await api.me();

    expect(authorization).toBeNull();
    expect(credentials).toBe("same-origin");
  });

  it("sends the CSRF header on every request, reads included", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get("/api/v1/market/markets", ({ request }) => {
        seen.push(request.headers.get("x-requested-with"));
        return HttpResponse.json(envelope(MARKETS));
      }),
      http.post("/api/v1/history/archive/:date", ({ request }) => {
        seen.push(request.headers.get("x-requested-with"));
        return HttpResponse.json({ status: "accepted", message: "ok", data: null }, { status: 202 });
      }),
    );

    await api.markets();
    await api.triggerArchive("2026-09-19");

    expect(seen).toEqual(["tradingmaster-ui", "tradingmaster-ui"]);
  });

  it("surfaces a rejected sign-in", async () => {
    server.use(
      http.post("/api/v1/auth/cookie/login", () =>
        HttpResponse.json({ detail: "LOGIN_BAD_CREDENTIALS" }, { status: 400 }),
      ),
    );

    const error = await api.login("trader@example.com", "wrong").catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(400);
  });

  it("reports a signed-out visitor as unauthorized", async () => {
    const error = await api.me().catch((e) => e);

    expect(error.isUnauthorized).toBe(true);
  });

  it("logs out through the cookie backend", async () => {
    let called = false;
    server.use(
      http.post("/api/v1/auth/cookie/logout", () => {
        called = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await api.logout();

    expect(called).toBe(true);
  });

  it("propagates a failed logout instead of pretending it worked", async () => {
    server.use(
      http.post("/api/v1/auth/cookie/logout", () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 }),
      ),
    );

    await expect(api.logout()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("archive trigger", () => {
  it("posts the date and returns the accepted envelope", async () => {
    server.use(
      http.post("/api/v1/history/archive/:date", ({ params }) =>
        HttpResponse.json(
          { status: "accepted", message: `Archive job started for ${params.date}`, data: null },
          { status: 202 },
        ),
      ),
    );

    const response = await api.triggerArchive("2026-09-19");

    expect(response.status).toBe("accepted");
    expect(response.message).toContain("2026-09-19");
  });

  it("surfaces the 401 when not signed in", async () => {
    server.use(
      http.post("/api/v1/history/archive/:date", () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 }),
      ),
    );

    const error = await api.triggerArchive("2026-09-19").catch((e) => e);

    expect(error.isUnauthorized).toBe(true);
  });
});
