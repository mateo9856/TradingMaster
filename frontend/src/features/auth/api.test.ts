import { authApi } from "@/features/auth/api";
import { historyApi } from "@/features/history/api";
import { marketsApi } from "@/features/markets/api";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/shared/http";
import { MARKETS, USER, envelope } from "@/test/handlers";
import { server } from "@/test/server";

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

    await expect(authApi.login("trader@example.com", "supersecret123")).resolves.toBeUndefined();

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

    await authApi.me();

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

    await marketsApi.markets();
    await historyApi.triggerArchive("2026-09-19");

    expect(seen).toEqual(["tradingmaster-ui", "tradingmaster-ui"]);
  });

  it("surfaces a rejected sign-in", async () => {
    server.use(
      http.post("/api/v1/auth/cookie/login", () =>
        HttpResponse.json({ detail: "LOGIN_BAD_CREDENTIALS" }, { status: 400 }),
      ),
    );

    const error = await authApi.login("trader@example.com", "wrong").catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(400);
  });

  it("reports a signed-out visitor as unauthorized", async () => {
    const error = await authApi.me().catch((e) => e);

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

    await authApi.logout();

    expect(called).toBe(true);
  });

  it("propagates a failed logout instead of pretending it worked", async () => {
    server.use(
      http.post("/api/v1/auth/cookie/logout", () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 }),
      ),
    );

    await expect(authApi.logout()).rejects.toBeInstanceOf(ApiError);
  });
});

