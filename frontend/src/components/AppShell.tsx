import { Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { CurrencySelect } from "@/components/CurrencySelect";
import { LanguageSelect } from "@/components/LanguageSelect";
import { LocalizedLink, LocalizedNavLink } from "@/components/LocalizedLink";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/lib/auth";
import { formatCash } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useTradingCapabilities, useTradingWallet } from "@/lib/trading";

const NAV = [
  { to: "/", key: "nav.live", end: true },
  { to: "/markets", key: "nav.markets" },
  { to: "/history", key: "nav.history" },
  { to: "/system", key: "nav.system" },
] as const;

export function AppShell() {
  const { user } = useAuth();
  const { t } = useTranslation();
  const trading = useTradingCapabilities();
  const wallet = useTradingWallet(Boolean(trading.data?.enabled));

  return (
    <div className="min-h-dvh bg-background">
      <header className="sticky top-0 z-10 border-b border-border bg-background/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <LocalizedNavLink to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            TradingMaster
            <Badge tone="info">{t("nav.mvp")}</Badge>
          </LocalizedNavLink>

          <nav aria-label={t("nav.main")} className="flex items-center gap-1 text-sm">
            {NAV.map((item) => (
              <LocalizedNavLink
                key={item.to}
                to={item.to}
                end={"end" in item ? item.end : undefined}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-1.5 transition-colors",
                    isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground",
                  )
                }
              >
                {t(item.key)}
              </LocalizedNavLink>
            ))}
            {trading.data?.enabled && <LocalizedNavLink to="/trades" className="rounded-md px-3 py-1.5">{t("trading.title")}</LocalizedNavLink>}
          </nav>

          <div className="ml-auto flex max-w-full flex-wrap items-center gap-x-3 gap-y-2 text-sm">
            {user && trading.data?.enabled && <div className="text-xs" aria-live="polite">
              <p>{t("payments.simulatedBalance")}: {wallet.isPending ? t("common.loading")
                : wallet.error ? t("payments.balanceError") : `${formatCash(wallet.data.balance)} ${t("trading.credits")}`}</p>
              <LocalizedLink to="/wallet" className="underline">{t("payments.addFunds")}</LocalizedLink>
            </div>}
            <LanguageSelect className="h-8 w-auto" />
            <CurrencySelect aria-label={t("nav.currency")} className="h-8 w-auto" />
            {user ? (
              <LocalizedNavLink to="/profile" className="max-w-full truncate text-muted-foreground hover:text-foreground">
                {user.email}
              </LocalizedNavLink>
            ) : (
              <LocalizedNavLink to="/login" className="text-muted-foreground hover:text-foreground">
                {t("nav.signIn")}
              </LocalizedNavLink>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
