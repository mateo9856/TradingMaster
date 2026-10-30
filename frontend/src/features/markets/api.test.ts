import { authApi } from "@/features/auth/api";

import { marketsApi } from "@/features/markets/api";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { ApiError, NetworkError } from "@/shared/http";
import { MARKETS, candle, envelope } from "@/test/handlers";
import { server } from "@/test/server";

describe("reading data", () => {
  it("unwraps the ApiResponse envelope", async () => {
    await expect(marketsApi.markets()).resolves.toEqual(MARKETS);
  });

  it("URL-encodes the ticker and passes the filters through", async () => {
    let requested: URL | null = null;
    server.use(
      http.get("/api/v1/market/candles/*", ({ request }) => {
        requested = new URL(request.url);
        return HttpResponse.json(envelope([candle()]));
      }),
    );

    await marketsApi.candles({ ticker: "BTC/USD", interval: "30s", exchange: "kraken", limit: 10 });

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

    await marketsApi.candles({ ticker: "BTC/USD", interval: "1m" });

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

    const error = await marketsApi.candles({ ticker: "BTC/USD", interval: "1m" }).catch((e) => e);

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

    const error = await marketsApi.candles({ ticker: "ETH/BTC", interval: "1m" }).catch((e) => e);

    expect(error.isValidation).toBe(true);
    expect(error.message).toBe("ticker: Unsupported quote currency in 'ETH/BTC'");
  });

  it.each([
    [401, "isUnauthorized"],
    [409, "isConflict"],
  ])("flags %i responses", async (status, flag) => {
    server.use(http.get("/api/v1/users/me", () => HttpResponse.json({ detail: "nope" }, { status })));

    const error = await authApi.me().catch((e) => e);

    expect(error[flag as keyof ApiError]).toBe(true);
  });

  it("reports an unreachable API as a network error", async () => {
    server.use(http.get("/api/v1/market/markets", () => HttpResponse.error()));

    await expect(marketsApi.markets()).rejects.toBeInstanceOf(NetworkError);
  });
});

