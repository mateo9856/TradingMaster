/**
 * Typed client for the TradingMaster API.
 *
 * Requests go to a relative /api path: the Vite dev server proxies them to
 * :8000, and in production the bundle is served from the same origin as the
 * API (by FastAPI or by nginx), so no base URL or CORS handling is needed.
 */

import type {
  ApiResponse,
  Candle,
  HistoryCandle,
  Market,
  User,
} from "./types";

/** An API call that came back with a non-2xx status. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** No rows for this query (an empty result, not a failure). */
  get isNotFound(): boolean {
    return this.status === 404;
  }

  /** Not logged in, or the token expired. */
  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  /** The API rejected the input (unsupported market, bad interval, …). */
  get isValidation(): boolean {
    return this.status === 422;
  }

  /** Already exists / clashes with an existing row. */
  get isConflict(): boolean {
    return this.status === 409;
  }
}

/** The API could not be reached at all (server down, network error). */
export class NetworkError extends Error {
  constructor(message = "Cannot reach the TradingMaster API") {
    super(message);
    this.name = "NetworkError";
  }
}

/**
 * Sent on every request so the API can tell a call from this UI apart from one
 * a third-party page triggered in the user's browser. A cross-site page cannot
 * add a custom header without a CORS preflight, which the API only grants to
 * configured origins — see app/auth/csrf.py.
 */
const CSRF_HEADER = "X-Requested-With";
const CSRF_VALUE = "tradingmaster-ui";

/** FastAPI returns `{"detail": "..."}` or `{"detail": [{msg, loc}, ...]}` (validation). */
function messageFromDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const { msg, loc } = item as { msg: string; loc?: unknown[] };
          const field = Array.isArray(loc) ? loc.at(-1) : undefined;
          return field ? `${field}: ${msg}` : msg;
        }
        return null;
      })
      .filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set(CSRF_HEADER, CSRF_VALUE);

  let response: Response;
  try {
    // The session is an http-only cookie the page cannot read; the browser
    // attaches it, and `same-origin` keeps it off any other host.
    response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  } catch (cause) {
    throw new NetworkError(cause instanceof Error ? cause.message : undefined);
  }

  const body =
    response.status === 204 || response.headers.get("content-length") === "0"
      ? null
      : await response.json().catch(() => null);

  if (!response.ok) {
    const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;
    throw new ApiError(
      response.status,
      messageFromDetail(detail, `${response.status} ${response.statusText}`),
      detail,
    );
  }
  return body as T;
}

/** Unwraps the `ApiResponse` envelope the API wraps its payloads in. */
async function requestData<T>(path: string, init?: RequestInit): Promise<T> {
  const body = await request<ApiResponse<T>>(path, init);
  return body.data;
}

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const api = {
  /** Markets currently collected, one entry per unified ticker. */
  markets(): Promise<Market[]> {
    return requestData<Market[]>("/api/v1/market/markets");
  },

  /**
   * Recent candles, newest first. Callers that chart them sort ascending —
   * see `toChartData` in ./chart-data.
   */
  candles(params: {
    ticker: string;
    interval: string;
    exchange?: string;
    limit?: number;
  }): Promise<Candle[]> {
    const { ticker, ...rest } = params;
    return requestData<Candle[]>(
      `/api/v1/market/candles/${encodeURIComponent(ticker)}${query(rest)}`,
    );
  },

  /** Archived candles for a date range (cold storage). */
  history(params: {
    ticker: string;
    date_from: string;
    date_to: string;
    interval?: string;
    exchange?: string;
    limit?: number;
  }): Promise<HistoryCandle[]> {
    const { ticker, ...rest } = params;
    return requestData<HistoryCandle[]>(
      `/api/v1/history/${encodeURIComponent(ticker)}${query(rest)}`,
    );
  },

  /** Triggers the end-of-day archive for one date. Requires a logged-in user. */
  triggerArchive(date: string): Promise<ApiResponse<null>> {
    return request<ApiResponse<null>>(`/api/v1/history/archive/${date}`, { method: "POST" });
  },

  health(): Promise<{ status: string }> {
    return request<{ status: string }>("/health");
  },

  /** Prometheus exposition format — parsed by ./metrics. */
  async metrics(): Promise<string> {
    const response = await fetch("/metrics").catch(() => {
      throw new NetworkError();
    });
    if (!response.ok) throw new ApiError(response.status, "Metrics are unavailable");
    return response.text();
  },

  /**
   * Signs in through the cookie backend: the API answers with a Set-Cookie and
   * no body, so no token ever reaches JavaScript. (The bearer login at
   * /api/v1/auth/jwt/login still exists for curl and integrations.)
   */
  async login(email: string, password: string): Promise<void> {
    // FastAPI Users' login is an OAuth2 password flow: form-encoded, with the
    // e-mail in the `username` field. Serialized to a string rather than passed
    // as URLSearchParams, which fetch rejects when it comes from another realm
    // (jsdom, some test runners).
    const body = new URLSearchParams({ username: email, password }).toString();
    await request<null>("/api/v1/auth/cookie/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
  },

  register(email: string, password: string): Promise<User> {
    return request<User>("/api/v1/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  },

  me(): Promise<User> {
    return request<User>("/api/v1/users/me");
  },

  /** Ends the session server-side; the response clears the cookie. */
  async logout(): Promise<void> {
    await request<null>("/api/v1/auth/cookie/logout", { method: "POST" });
  },
};
