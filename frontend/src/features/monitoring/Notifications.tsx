import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/features/auth/auth";
import { LocalizedLink, useLocalizedPath } from "@/shared/LocalizedLink";
import { parseUtc } from "@/shared/format";
import { Button, buttonClasses } from "@/shared/ui/button";
import { monitoringApi, type AlertPage, type Signal } from "./api";
import { useMonitoringAlerts } from "./hooks";
import { isCurrentNotification, notificationBody, notificationTitle } from "./notification-text";
import { useNotificationFeed } from "./useNotificationFeed";

function BellIcon() {
  return <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" />
  </svg>;
}

function Summary({ signal }: { signal: Signal }) {
  const { t } = useTranslation();
  return <><p className="font-semibold">{notificationTitle(signal, t)}</p>
    <p className="mt-1 text-sm text-muted-foreground">{notificationBody(signal, t)}</p>
    <time className="mt-1 block text-xs text-muted-foreground" dateTime={parseUtc(signal.created_at).toISOString()}>{parseUtc(signal.created_at).toLocaleString()}</time></>;
}

export function Notifications() {
  const { user } = useAuth();
  return user ? <AccountNotifications key={user.id} userId={user.id} /> : null;
}

function AccountNotifications({ userId }: { userId: string }) {
  const { t } = useTranslation();
  const inbox = useMonitoringAlerts();
  const client = useQueryClient();
  const navigate = useNavigate();
  const localize = useLocalizedPath();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ left: 16, top: 64, maxHeight: 400 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLElement>(null);
  const alive = useRef(true);
  const panelId = `notifications-${userId}`;
  const unread = inbox.data?.unread_count;
  const label = t(unread === undefined ? "notifications.bell" : "notifications.bellUnread", { count: unread });
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const place = () => {
    const rect = root.current?.querySelector("button")?.getBoundingClientRect();
    if (!rect) return;
    const width = Math.min(384, window.innerWidth - 32);
    const top = Math.min(rect.bottom + 8, Math.max(16, window.innerHeight - 160));
    setPosition({ left: Math.max(16, Math.min(rect.right - width, window.innerWidth - width - 16)),
      top, maxHeight: Math.max(40, window.innerHeight - top - 16) });
  };
  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector("button")?.focus();
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target) && !panel.current?.contains(event.target)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false); root.current?.querySelector("button")?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);

  const view = async (signal: Signal): Promise<boolean> => {
    if (busy) return false;
    setBusy(true); setError("");
    try {
      if (!signal.read_at) await monitoringApi.read(signal.id);
      await client.invalidateQueries({ queryKey: ["monitoring", userId, "alerts"] });
      if (!alive.current) return false;
      setOpen(false);
      navigate(localize(`/monitoring?tab=alerts&notification=${signal.id}`));
      return true;
    } catch (caught) {
      if (alive.current) setError((caught as Error).message);
      return false;
    } finally { if (alive.current) setBusy(false); }
  };
  return <div ref={root} className="relative">
    <Button type="button" variant="secondary" className="relative h-9 w-10 px-0" aria-label={label}
      aria-expanded={open} aria-controls={panelId} onClick={() => { place(); setOpen(!open); }}>
      <BellIcon />
      {unread ? <span aria-hidden="true" className="absolute -right-2 -top-2 min-w-5 rounded-full bg-primary px-1 text-[10px] font-semibold leading-5 text-primary-foreground">{unread > 99 ? "99+" : unread}</span> : null}
    </Button>
    {open && createPortal(<section ref={panel} id={panelId} aria-label={t("notifications.recent")} style={position}
      className="fixed z-50 w-96 max-w-[calc(100vw-2rem)] overflow-y-auto overscroll-contain rounded-lg border border-border bg-card p-4 text-card-foreground shadow-xl">
      <div className="mb-3 flex items-center justify-between gap-2"><h2 className="font-semibold">{t("notifications.recent")}</h2>
        <Button type="button" variant="ghost" size="sm" aria-label={t("notifications.close")} onClick={() => { setOpen(false); root.current?.querySelector("button")?.focus(); }}>×</Button></div>
      {inbox.isPending && <p>{t("common.loading")}</p>}
      {inbox.error && <><p role="alert">{t("notifications.loadFailed")}</p>
        <Button type="button" size="sm" variant="secondary" onClick={() => void inbox.refetch()}>{t("common.retry")}</Button></>}
      {error && <p role="alert">{error}</p>}
      {inbox.data?.items.length === 0 && <p className="text-sm">{t("monitoring.emptyAlerts")}</p>}
      <ul className="divide-y divide-border">{inbox.data?.items.slice(0, 8).map((signal) => <li key={signal.id} className="py-3">
        <div className="flex items-start gap-2">{!signal.read_at && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary" aria-label={t("notifications.unread")} />}
          <div className="min-w-0"><Summary signal={signal} /><Button type="button" variant="secondary" size="sm" className="mt-2" disabled={busy} onClick={() => void view(signal)}>{t("notifications.view")}</Button></div></div>
      </li>)}</ul>
      <LocalizedLink to="/monitoring?tab=alerts" className={buttonClasses({ className: "mt-3 w-full" })} onClick={() => setOpen(false)}>{t("notifications.viewAll")}</LocalizedLink>
    </section>, document.body)}
    {inbox.data && <LivePopups userId={userId} baseline={inbox.data} view={view} busy={busy} error={error} />}
  </div>;
}

function LivePopups({ userId, baseline, view, busy, error }: {
  userId: string; baseline: AlertPage; view: (signal: Signal) => Promise<boolean>; busy: boolean; error: string;
}) {
  const { t } = useTranslation();
  const feed = useNotificationFeed(userId, baseline);
  const client = useQueryClient();
  const seen = useRef(new Set<string>());
  const [popups, setPopups] = useState<Signal[]>([]);
  const [overflow, setOverflow] = useState(0);
  useEffect(() => {
    if (!feed.data) return;
    const incoming = feed.data.items.filter((signal) => !seen.current.has(signal.id) && isCurrentNotification(signal));
    for (const signal of feed.data.items) seen.current.add(signal.id);
    // The cursor is monotonic, so deduplication memory only needs the last batch.
    if (seen.current.size > 1000) seen.current = new Set(feed.data.items.map((signal) => signal.id));
    if (!incoming.length) return;
    void client.invalidateQueries({ queryKey: ["monitoring", userId, "alerts"] });
    setPopups((current) => [...current, ...incoming].slice(0, 3));
    // Keep the remaining alerts accessible without covering the screen in cards.
    setOverflow((current) => current + Math.max(0, incoming.length - Math.max(0, 3 - popups.length)));
  }, [feed.data, popups.length, client, userId]);
  const dismiss = (id: string) => setPopups((current) => current.filter((signal) => signal.id !== id));
  if (!popups.length && !overflow) return null;
  return createPortal(<section aria-label={t("notifications.newAlerts")} className="fixed bottom-4 right-4 z-40 max-h-[75dvh] w-96 max-w-[calc(100vw-2rem)] space-y-3 overflow-y-auto overscroll-contain">
    {popups.map((signal) => <div key={signal.id} role="status" className="rounded-lg border border-primary bg-card p-4 text-card-foreground shadow-xl">
      <div className="flex items-start justify-between gap-3"><div className="min-w-0"><Summary signal={signal} /></div>
        <Button type="button" variant="ghost" size="sm" className="shrink-0" aria-label={t("notifications.dismiss", { title: notificationTitle(signal, t) })} onClick={() => dismiss(signal.id)}>×</Button></div>
      {error && <p role="alert" className="mt-2 text-sm">{error}</p>}
      <Button type="button" className="mt-3" size="sm" disabled={busy} onClick={async () => { if (await view(signal)) dismiss(signal.id); }}>{t("notifications.view")}</Button>
    </div>)}
    {overflow > 0 && <div role="status" className="rounded-lg border border-border bg-card p-4 text-card-foreground shadow-xl">
      <p>{t("notifications.more", { count: overflow })}</p><div className="mt-2 flex flex-wrap gap-2">
        <LocalizedLink to="/monitoring?tab=alerts" className={buttonClasses({ size: "sm" })} onClick={() => { setPopups([]); setOverflow(0); }}>{t("notifications.viewAll")}</LocalizedLink>
        <Button type="button" variant="secondary" size="sm" onClick={() => setOverflow(0)}>{t("notifications.dismissAll")}</Button>
      </div></div>}
  </section>, document.body);
}
