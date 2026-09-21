import { Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { HistoryPage } from "@/pages/HistoryPage";
import { LivePage } from "@/pages/LivePage";
import { LoginPage } from "@/pages/LoginPage";
import { ProfilePage } from "@/pages/ProfilePage";
import { SystemPage } from "@/pages/SystemPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<LivePage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="system" element={<SystemPage />} />
        <Route path="login" element={<LoginPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="*" element={<p className="text-sm text-muted-foreground">Page not found.</p>} />
      </Route>
    </Routes>
  );
}
