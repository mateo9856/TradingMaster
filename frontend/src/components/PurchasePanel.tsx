import { useTranslation } from "react-i18next";

import { LocalizedLink } from "@/components/LocalizedLink";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { useTradingCapabilities } from "@/lib/trading";

export function PurchasePanel({ ticker, exchange }: { ticker: string; exchange: string }) {
  const capabilities = useTradingCapabilities();
  const { user, loading } = useAuth();
  const { t } = useTranslation();
  const waiting = loading || capabilities.isPending;
  const unavailable = waiting || capabilities.isError || !capabilities.data?.enabled;
  const search = new URLSearchParams({ ticker, exchange, budget: "100" });
  return <div className="flex max-w-xs flex-col items-end gap-1 text-right">
    {unavailable ? <Button disabled>{t("trading.buy")}</Button> : (
      <LocalizedLink to={user ? `/checkout?${search}` : "/login"}
        className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {t(user ? "trading.buy" : "trading.signIn")}
      </LocalizedLink>
    )}
    <p className="text-xs text-muted-foreground" role="status">
      {waiting ? t("common.loading") : capabilities.isError ? t("payments.tradingUnavailable")
        : !capabilities.data?.enabled ? t("trading.disabled") : t("trading.simulated")}
    </p>
    {capabilities.isError && <Button variant="secondary" size="sm" disabled={capabilities.isFetching}
      onClick={() => void capabilities.refetch()}>{t("common.retry")}</Button>}
  </div>;
}
