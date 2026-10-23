/**
 * Sign in / register using the API's http-only session cookie.
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
import { ApiError, NetworkError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Mode = "login" | "register";
type FormField = "email" | "password" | "repeatPassword";

const PASSWORD_REASONS: Record<string, string> = {
  "Password must be at least 12 characters.": "login.passwordLength",
  "Password must be at most 128 characters.": "login.passwordLength",
  "That password is too common. Choose something less guessable.": "login.passwordTooCommon",
  "Password must not contain your email address.": "login.passwordContainsEmail",
  "Password must not be your email address.": "login.passwordContainsEmail",
  "Password must not be a single repeated character.": "login.passwordRepeated",
};

function failureKey(error: unknown, mode: Mode): string {
  if (error instanceof NetworkError) return "login.networkError";
  if (error instanceof ApiError) {
    if (error.status === 429) return "login.tooManyAttempts";
    if (error.status === 400) {
      if (error.detail === "LOGIN_BAD_CREDENTIALS") return "login.wrongCredentials";
      if (error.detail === "LOGIN_USER_NOT_VERIFIED") return "login.notVerified";
      if (error.detail === "REGISTER_USER_ALREADY_EXISTS") return "login.emailExists";
      const detail = error.detail;
      if (detail && typeof detail === "object" && "code" in detail && detail.code === "REGISTER_INVALID_PASSWORD") {
        return "reason" in detail && typeof detail.reason === "string" && Object.hasOwn(PASSWORD_REASONS, detail.reason)
          ? PASSWORD_REASONS[detail.reason]
          : "login.passwordRejected";
      }
    }
    if (error.status === 422) return "login.invalidForm";
  }
  return mode === "login" ? "login.signInFailed" : "login.registrationFailed";
}

export function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const localize = useLocalizedPath();
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [repeatPassword, setRepeatPassword] = useState("");
  const [touched, setTouched] = useState<Partial<Record<FormField, boolean>>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const errors: Partial<Record<FormField, string>> = {};
  if (!email.trim()) errors.email = "login.emailRequired";
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) errors.email = "login.invalidEmail";
  if (!password) errors.password = "login.passwordRequired";
  else if (mode === "register" && (Array.from(password).length < 12 || Array.from(password).length > 128)) {
    errors.password = "login.passwordLength";
  }
  if (mode === "register") {
    if (!repeatPassword) errors.repeatPassword = "login.repeatPasswordRequired";
    else if (repeatPassword !== password) errors.repeatPassword = "login.passwordMismatch";
  }

  const fieldError = (field: FormField) => touched[field] && errors[field] ? t(errors[field]) : undefined;
  const markTouched = (field: FormField) => setTouched((current) => ({ ...current, [field]: true }));

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    setError(null);
    const fields: FormField[] = mode === "login" ? ["email", "password"] : ["email", "password", "repeatPassword"];
    setTouched({ email: true, password: true, repeatPassword: mode === "register" });
    const invalid = fields.find((field) => errors[field]);
    if (invalid) {
      const input = event.currentTarget.elements.namedItem(invalid);
      if (input instanceof HTMLInputElement) input.focus();
      return;
    }
    setBusy(true);
    try {
      if (mode === "login") {
        await login(email.trim(), password);
      } else {
        await register(email.trim(), password);
      }
      navigate(localize("/profile"));
    } catch (caught) {
      setError(failureKey(caught, mode));
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
          <form noValidate onSubmit={submit} className="flex flex-col gap-3">
            <Field label={t("login.email")} error={fieldError("email")}>
              {(id) => (
                <Input
                  id={id}
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  disabled={busy}
                  aria-invalid={Boolean(fieldError("email"))}
                  aria-describedby={fieldError("email") ? `${id}-error` : undefined}
                  value={email}
                  onBlur={() => markTouched("email")}
                  onChange={(event) => { setEmail(event.target.value); setError(null); }}
                />
              )}
            </Field>
            <Field label={t("login.password")} hint={mode === "register" ? t("login.passwordHint") : undefined} error={fieldError("password")}>
              {(id) => (
                <Input
                  id={id}
                  name="password"
                  type="password"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  required
                  disabled={busy}
                  aria-invalid={Boolean(fieldError("password"))}
                  aria-describedby={[mode === "register" ? `${id}-hint` : "", fieldError("password") ? `${id}-error` : ""].filter(Boolean).join(" ") || undefined}
                  value={password}
                  onBlur={() => markTouched("password")}
                  onChange={(event) => { setPassword(event.target.value); setError(null); }}
                />
              )}
            </Field>

            {mode === "register" && (
              <Field label={t("login.repeatPassword")} error={fieldError("repeatPassword")}>
                {(id) => (
                  <Input
                    id={id}
                    name="repeatPassword"
                    type="password"
                    autoComplete="new-password"
                    required
                    disabled={busy}
                    aria-invalid={Boolean(fieldError("repeatPassword"))}
                    aria-describedby={fieldError("repeatPassword") ? `${id}-error` : undefined}
                    value={repeatPassword}
                    onBlur={() => markTouched("repeatPassword")}
                    onChange={(event) => { setRepeatPassword(event.target.value); setError(null); }}
                  />
                )}
              </Field>
            )}

            {error ? <Alert tone="danger">{t(error)}</Alert> : null}

            <Button type="submit" disabled={busy}>
              {busy ? t("login.wait") : mode === "login" ? t("login.signIn") : t("login.register")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setRepeatPassword("");
                setTouched({});
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
