import { tradingApi } from "@/features/trading/api";
import { useQuery } from "@tanstack/react-query";

import type { TFunction } from "i18next";

import { ApiError } from "@/shared/http";
import { useAuth } from "@/features/auth/auth";

export function paymentError(error: unknown, t: TFunction): string {
  const message = (error as Error).message;
  const keys: Record<string, string> = {
    "Insufficient credits": "insufficientCredits",
    "Insufficient simulated payment funds": "insufficientFunds",
    "Insufficient available credit": "insufficientCredit",
    "Payment transaction limit exceeded": "limitExceeded",
    "Quote expired or was already used; request a new preview": "expired",
    "Idempotency key was already used for a different request": "requestConflict",
    "Wallet balance limit exceeded": "walletLimit",
    "Initialize the trading wallet first": "initializeFirst",
    "Quote not found": "quoteMissing",
    "Quote does not match this action": "quoteMismatch",
  };
  if (keys[message]) return t(`payments.${keys[message]}`);
  if (error instanceof ApiError && error.status === 422) return t("payments.invalidInput");
  return message;
}

export function useTradingCapabilities() {
  return useQuery({ queryKey: ["trading-capabilities"], queryFn: tradingApi.tradingCapabilities, staleTime: 60_000 });
}

export function useTradingWallet(enabled: boolean) {
  const { user } = useAuth();
  return useQuery({
    queryKey: ["trading", user?.id, "wallet"],
    queryFn: tradingApi.tradingWallet,
    enabled: enabled && Boolean(user),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: "always",
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}

export function usePaymentAccounts(enabled: boolean) {
  const { user } = useAuth();
  return useQuery({
    queryKey: ["trading", user?.id, "payment-accounts"], queryFn: tradingApi.paymentAccounts,
    enabled: enabled && Boolean(user), retry: false, refetchOnWindowFocus: "always",
    refetchInterval: 30_000, refetchIntervalInBackground: false,
  });
}
