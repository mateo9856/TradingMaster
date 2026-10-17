/**
 * Sign in / register. FastAPI Users issues a JWT that the API client attaches
 * to every later request; reading data never needs one.
 */

import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useLocalizedPath } from "@/components/LocalizedLink";
import { Seo } from "@/components/Seo";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/field";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const localize = useLocalizedPath();
  const { t } = useTranslation();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password);
      }
      navigate(localize("/profile"));
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 400) {
        setError(
          mode === "login"
            ? t("login.wrongCredentials")
            : t("login.registrationFailed", { message: caught.message }),
        );
      } else {
        setError((caught as Error).message);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-md">
      <Seo title={t("seo.login_title")} noindex />
      <Card>
        <CardHeader
          level={1}
          title={mode === "login" ? t("login.signIn") : t("login.createAccount")}
          description={t("login.description")}
        />
        <CardBody>
          <form onSubmit={submit} className="flex flex-col gap-3">
            <Field label={t("login.email")}>
              {(id) => (
                <Input
                  id={id}
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              )}
            </Field>
            <Field label={t("login.password")} hint={mode === "register" ? t("login.passwordHint") : undefined}>
              {(id) => (
                <Input
                  id={id}
                  type="password"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              )}
            </Field>

            {error ? <Alert tone="danger">{error}</Alert> : null}

            <Button type="submit" disabled={busy}>
              {busy ? t("login.wait") : mode === "login" ? t("login.signIn") : t("login.register")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setError(null);
              }}
            >
              {mode === "login" ? t("login.toRegister") : t("login.toSignIn")}
            </Button>
          </form>
        </CardBody>
      </Card>
    </div>
  );
}
