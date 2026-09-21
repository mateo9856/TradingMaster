import { useState } from "react";
import { Navigate } from "react-router-dom";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { useAuth } from "@/lib/auth";

export function ProfilePage() {
  const { user, loading, logout } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const signOut = async () => {
    setBusy(true);
    setError(null);
    try {
      await logout();
    } catch (caught) {
      // The session may still be live, so don't pretend it ended.
      setError(`Could not sign out: ${(caught as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!user) return <Navigate to="/login" replace />;

  return (
    <div className="mx-auto w-full max-w-md">
      <Card>
        <CardHeader title="Your account" description="From GET /api/v1/users/me" />
        <CardBody className="flex flex-col gap-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="text-muted-foreground">E-mail</span>
            <span className="font-medium">{user.email}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-muted-foreground">Status</span>
            <span className="flex gap-2">
              <Badge tone={user.is_active ? "success" : "danger"}>
                {user.is_active ? "active" : "inactive"}
              </Badge>
              {user.is_superuser ? <Badge tone="info">admin</Badge> : null}
              {user.is_verified ? <Badge>verified</Badge> : null}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-muted-foreground">User id</span>
            <span className="font-mono text-xs">{user.id}</span>
          </div>
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Button variant="secondary" onClick={signOut} disabled={busy}>
            {busy ? "Signing out…" : "Sign out"}
          </Button>
        </CardBody>
      </Card>
    </div>
  );
}
