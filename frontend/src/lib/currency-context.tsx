/**
 * The display currency, shared by every screen.
 *
 * Resolution order and the reasons for it are in ./currency.ts. A choice made
 * with the header picker is remembered in this browser and, for a signed-in
 * user, saved to the profile so it follows them to other devices.
 */

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "./api";
import { useAuth } from "./auth";
import {
  BASE_CURRENCY,
  browserEnvironment,
  detectCurrency,
  readStoredCurrency,
  storeCurrency,
} from "./currency";
import type { CurrencyInfo } from "./types";

interface CurrencyState {
  /** The currency prices are shown in, e.g. "PLN". */
  currency: string;
  /** Everything the API can convert to (always includes USD). */
  currencies: CurrencyInfo[];
  /** Details of the current currency (rate, date), if known. */
  info: CurrencyInfo | undefined;
  /** False until the list of supported currencies has loaded — don't fetch prices before. */
  ready: boolean;
  setCurrency: (code: string) => void;
}

const USD_ONLY: CurrencyInfo[] = [
  { code: BASE_CURRENCY, name: "US dollar", units_per_usd: "1.00000000", rate_date: null },
];

const CurrencyContext = createContext<CurrencyState | null>(null);

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [sessionChoice, setSessionChoice] = useState<string | null>(null);
  const [stored] = useState(readStoredCurrency);

  const currenciesQuery = useQuery({
    queryKey: ["currencies"],
    queryFn: api.currencies,
    staleTime: 60 * 60_000,      // ECB rates change once a day
    retry: 1,
  });
  // If the list can't be loaded, USD still works — it needs no rate.
  const currencies = currenciesQuery.data?.currencies ?? USD_ONLY;
  const ready = !authLoading && !currenciesQuery.isPending;

  const currency = useMemo(() => {
    const { timeZone, languages } = browserEnvironment();
    return detectCurrency({
      supported: currencies.map((c) => c.code),
      sessionChoice,
      profile: user?.preferred_currency,
      stored,
      timeZone,
      languages,
      serverDefault: currenciesQuery.data?.default,
    });
  }, [currencies, sessionChoice, user?.preferred_currency, stored, currenciesQuery.data?.default]);

  const setCurrency = useCallback(
    (code: string) => {
      setSessionChoice(code);
      storeCurrency(code);
      if (user) {
        api.updateMe({ preferred_currency: code }).catch((error) => {
          // Still applied here and remembered in this browser — only the profile copy failed.
          console.warn("Could not save the preferred currency:", error);
        });
      }
    },
    [user],
  );

  const value = useMemo(
    () => ({
      currency,
      currencies,
      info: currencies.find((c) => c.code === currency),
      ready,
      setCurrency,
    }),
    [currency, currencies, ready, setCurrency],
  );

  return <CurrencyContext.Provider value={value}>{children}</CurrencyContext.Provider>;
}

export function useCurrency(): CurrencyState {
  const context = useContext(CurrencyContext);
  if (!context) throw new Error("useCurrency must be used inside <CurrencyProvider>");
  return context;
}
