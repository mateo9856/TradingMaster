import { useState } from "react";
import { Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useLocalizedPath } from "@/components/LocalizedLink";
import { Seo } from "@/components/Seo";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { CurrencySelect } from "@/components/CurrencySelect";
import { Field } from "@/components/ui/field";
import { useAuth } from "@/lib/auth";

export function ProfilePage() {
  const { user, loading, logout } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { t } = useTranslation();
  const localize = useLocalizedPath();

  const signOut = async () => {
    setBusy(true);
    setError(null);
    try {
      await logout();
    } catch (caught) {
      // The session may still be live, so don't pretend it ended.
      setError(t("profile.signOutFailed", { message: (caught as Error).message }));
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>;
  if (!user) return <Navigate to={localize("/login")} replace />;

  return (
    <div className="mx-auto w-full max-w-md">
      <Seo title={t("seo.profile_title")} noindex />
      <Card>
        <CardHeader level={1} title={t("profile.title")} description={t("profile.description")} />
        <CardBody className="flex flex-col gap-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="text-muted-foreground">{t("profile.email")}</span>
            <span className="font-medium">{user.email}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-muted-foreground">{t("profile.status")}</span>
            <span className="flex gap-2">
              <Badge tone={user.is_active ? "success" : "danger"}>
                {user.is_active ? t("profile.active") : t("profile.inactive")}
              </Badge>
              {user.is_superuser ? <Badge tone="info">{t("profile.admin")}</Badge> : null}
              {user.is_verified ? <Badge>{t("profile.verified")}</Badge> : null}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-muted-foreground">{t("profile.userId")}</span>
            <span className="font-mono text-xs">{user.id}</span>
          </div>
          <Field label={t("profile.preferredCurrency")} hint={t("profile.preferredCurrencyHint")}>
            {(id) => <CurrencySelect id={id} />}
          </Field>
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Button variant="secondary" onClick={signOut} disabled={busy}>
            {busy ? t("profile.signingOut") : t("profile.signOut")}
          </Button>
        </CardBody>
      </Card>
    </div>
  );
}
