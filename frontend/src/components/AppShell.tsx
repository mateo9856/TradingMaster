import { NavLink, Outlet } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Live", end: true },
  { to: "/history", label: "History" },
  { to: "/system", label: "System" },
];

export function AppShell() {
  const { user } = useAuth();

  return (
    <div className="min-h-dvh bg-background">
      <header className="sticky top-0 z-10 border-b border-border bg-background/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <NavLink to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            TradingMaster
            <Badge tone="info">MVP</Badge>
          </NavLink>

          <nav className="flex items-center gap-1 text-sm">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-1.5 transition-colors",
                    isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto text-sm">
            {user ? (
              <NavLink to="/profile" className="text-muted-foreground hover:text-foreground">
                {user.email}
              </NavLink>
            ) : (
              <NavLink to="/login" className="text-muted-foreground hover:text-foreground">
                Sign in
              </NavLink>
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
