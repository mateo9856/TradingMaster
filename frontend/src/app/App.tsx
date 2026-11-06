import { Route, Routes } from "react-router-dom";

import { AppShell } from "@/app/AppShell";
import { LanguageLayout } from "@/app/LanguageLayout";
import { HistoryPage } from "@/features/history/HistoryPage";
import { LivePage } from "@/features/markets/LivePage";
import { LoginPage } from "@/features/auth/LoginPage";
import { MarketsPage } from "@/features/markets/MarketsPage";
import { NotFoundPage } from "@/app/NotFoundPage";
import { ProfilePage } from "@/features/auth/ProfilePage";
import { SystemPage } from "@/features/system/SystemPage";
import { TradesPage } from "@/features/trading/TradesPage";
import { CheckoutPage } from "@/features/trading/CheckoutPage";
import { WalletPage } from "@/features/trading/WalletPage";
import { MonitoringPage } from "@/features/monitoring/MonitoringPage";

/**
 * Every route exists once per language: unprefixed for English, /pl/…, /de/…
 * for the rest (src/lib/i18n.ts). The server knows the same routes — keep
 * app/seo.py STATIC_PAGES in step when adding one.
 */
export function App() {
  return (
    <Routes>
      <Route path="/:lang?" element={<LanguageLayout />}>
        <Route element={<AppShell />}>
          <Route index element={<LivePage />} />
          <Route path="markets" element={<MarketsPage />} />
          <Route path="markets/:slug" element={<LivePage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="system" element={<SystemPage />} />
          <Route path="login" element={<LoginPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="trades" element={<TradesPage />} />
          <Route path="checkout" element={<CheckoutPage />} />
          <Route path="wallet" element={<WalletPage />} />
          <Route path="monitoring" element={<MonitoringPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
