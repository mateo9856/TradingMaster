import { useTranslation } from "react-i18next";

import { LocalizedLink } from "@/shared/LocalizedLink";
import { Button, buttonClasses } from "@/shared/ui/button";
import { useAuth } from "@/features/auth/auth";
import { useTradingCapabilities } from "@/features/trading/trading";

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
        className={buttonClasses()}>
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
