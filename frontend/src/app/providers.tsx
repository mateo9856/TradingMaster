import { useCallback } from "react";
import type { ReactNode } from "react";

import { AuthProvider, useAuth } from "@/features/auth/auth";
import { authApi } from "@/features/auth/api";
import { CurrencyProvider } from "@/shared/currency-context";

function SessionCurrencyProvider({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const savePreference = useCallback((code: string) => authApi.updateMe({ preferred_currency: code }), []);
  return <CurrencyProvider profileCurrency={user?.preferred_currency} authLoading={loading}
    savePreference={user ? savePreference : undefined}>{children}</CurrencyProvider>;
}

export function AppProviders({ children }: { children: ReactNode }) {
  return <AuthProvider><SessionCurrencyProvider>{children}</SessionCurrencyProvider></AuthProvider>;
}
