/**
 * Session state for the UI.
 *
 * Reading market data is public; every change (manual candle insert, archive
 * trigger, market management) needs a session. The UI therefore always renders,
 * and only gates the actions.
 *
 * The session is an http-only cookie set by the API — nothing readable is kept
 * in the page, so there is no token here to store, pass around or leak.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { ApiError, api } from "./api";
import type { User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // The session cookie is http-only, so the page cannot inspect it — ask the
  // API who we are instead. A 401 simply means "signed out".
  useEffect(() => {
    let cancelled = false;

    api
      .me()
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch((error) => {
        if (!(error instanceof ApiError && error.isUnauthorized)) {
          console.warn("Could not restore the session:", error);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    await api.login(email, password);
    setUser(await api.me());
  }, []);

  const register = useCallback(
    async (email: string, password: string) => {
      await api.register(email, password);
      await login(email, password); // registration doesn't return a token
    },
    [login],
  );

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch (error) {
      // A 401 means the session was already gone (expired, or ended elsewhere)
      // — the user is signed out either way. Anything else is a real failure:
      // the cookie may still be valid, so say so rather than fake success.
      if (!(error instanceof ApiError && error.isUnauthorized)) throw error;
    }
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
