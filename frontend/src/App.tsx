import { Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { LanguageLayout } from "@/components/LanguageLayout";
import { HistoryPage } from "@/pages/HistoryPage";
import { LivePage } from "@/pages/LivePage";
import { LoginPage } from "@/pages/LoginPage";
import { MarketsPage } from "@/pages/MarketsPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { ProfilePage } from "@/pages/ProfilePage";
import { SystemPage } from "@/pages/SystemPage";
import { TradesPage } from "@/pages/TradesPage";

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
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
