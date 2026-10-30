import { request } from "@/shared/http";
import type { User } from "./types";

export const authApi = {
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

  /** Updates the signed-in user's own profile (e.g. the preferred currency). */
  updateMe(patch: Partial<Pick<User, "preferred_currency">>): Promise<User> {
    return request<User>("/api/v1/users/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
  },

  /** Ends the session server-side; the response clears the cookie. */
  async logout(): Promise<void> {
    await request<null>("/api/v1/auth/cookie/logout", { method: "POST" });
  },
};
