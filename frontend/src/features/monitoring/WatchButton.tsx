import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { LocalizedLink } from "@/shared/LocalizedLink";
import { Button, buttonClasses } from "@/shared/ui/button";
import { monitoringApi } from "./api";
import { useMonitoring, useMonitoringSettings } from "./hooks";

export function WatchButton({ exchange, ticker }: { exchange: string; ticker: string }) {
  const { user, refresh } = useMonitoring();
  const settings = useMonitoringSettings();
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLDivElement>(null);
  const title = useId();
  const description = useId();
  useEffect(() => {
    const element = dialog.current;
    if (confirming && element && !element.open) element.showModal();
    return () => { if (element?.open) element.close(); };
  }, [confirming]);

  const close = () => {
    setConfirming(false);
    trigger.current?.querySelector("button")?.focus();
  };
  const save = async (enable: boolean) => {
    if (busy) return;
    setBusy(true); setMessage(""); setError("");
    try {
      await monitoringApi.watch(exchange, ticker, enable);
      await refresh(); setMessage(t(enable || settings.data?.enabled ? "monitoring.addedEnabled" : "monitoring.addedPaused"));
      close();
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  };
  if (!user) return <LocalizedLink to="/login" className={buttonClasses({ variant: "secondary" })}>{t("monitoring.signIn")}</LocalizedLink>;
  return <div className="flex max-w-56 flex-col items-start gap-1" ref={trigger}>
    <Button variant="secondary" disabled={busy || settings.isPending || settings.isError} onClick={() => {
      setError(""); setMessage("");
      if (settings.data?.enabled) void save(false);
      else setConfirming(true);
    }}>{t("monitoring.watch")}</Button>
    {settings.isPending && <p className="text-xs" role="status">{t("common.loading")}</p>}
    {settings.error && <><p className="text-xs" role="alert">{settings.error.message}</p>
      <Button size="sm" variant="secondary" onClick={() => void settings.refetch()}>{t("common.retry")}</Button></>}
    {message && <p className="text-xs" role="status">{message} <LocalizedLink to="/monitoring" className="underline">{t("monitoring.title")}</LocalizedLink></p>}
    {error && !confirming && <p className="text-xs" role="alert">{error}</p>}
    <dialog ref={dialog} aria-labelledby={title} aria-describedby={description}
      onCancel={(event) => { event.preventDefault(); if (!busy) close(); }} onClose={() => setConfirming(false)}
      className="fixed inset-0 m-auto max-h-[90dvh] w-[calc(100%_-_2rem)] max-w-md overflow-auto rounded-lg border border-border bg-card p-6 text-card-foreground shadow-lg backdrop:bg-black/40">
      <h2 id={title} className="text-lg font-semibold">{t("monitoring.watchDialogTitle")}</h2>
      <p className="my-3 text-sm" id={description}>{t("monitoring.watchDialogBody", { ticker })}</p>
      {error && <p className="mb-3 text-sm" role="alert">{error}</p>}
      <div className="flex flex-col items-start gap-2">
        <Button disabled={busy} onClick={() => void save(true)}>{t("monitoring.watchEnable")}</Button>
        <Button variant="secondary" disabled={busy} onClick={() => void save(false)}>{t("monitoring.watchPaused")}</Button>
        <Button variant="ghost" disabled={busy} onClick={close}>{t("monitoring.cancel")}</Button>
      </div>
    </dialog>
  </div>;
}
