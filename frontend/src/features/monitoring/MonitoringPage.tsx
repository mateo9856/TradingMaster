import { useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/features/auth/auth";
import { useTradingCapabilities } from "@/features/trading/trading";
import { LocalizedLink, useLocalizedPath } from "@/shared/LocalizedLink";
import { Seo } from "@/shared/Seo";
import { Alert } from "@/shared/ui/alert";
import { Button, buttonClasses } from "@/shared/ui/button";
import { Card, CardBody } from "@/shared/ui/card";
import { monitoringApi, type Target } from "./api";
import { useMonitoring, useMonitoringAlerts, useMonitoringSettings } from "./hooks";
import { notificationTitle } from "./notification-text";

const price = (value?: string | null) => value == null ? "—" : `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 8 })}`;
const percent = (value?: string) => value == null ? "—" : `${Number(value).toFixed(2)}%`;
const stamp = (value?: string | null) => value ? new Date(value.endsWith("Z") ? value : `${value}Z`).toLocaleString() : "—";

export function MonitoringPage() {
  const { user, loading } = useAuth();
  const { t } = useTranslation();
  const localize = useLocalizedPath();
  if (loading) return <p>{t("common.loading")}</p>;
  if (!user) return <Navigate to={localize("/login")} replace />;
  return <><Seo title={t("monitoring.title")} noindex /><Panel key={user.id} /></>;
}

function Panel() {
  const { t } = useTranslation();
  const { key, refresh } = useMonitoring();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "holdings" ? "holdings" : params.get("tab") === "alerts" ? "alerts" : "watchlist";
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const settings = useMonitoringSettings();
  const capabilities = useTradingCapabilities();
  const alerts = useMonitoringAlerts(tab === "alerts" ? offset : 0);
  const targets = useQuery({ queryKey: [...key, "targets", tab, offset], queryFn: () => tab === "holdings" ? monitoringApi.holdings(offset) : monitoringApi.watchlist(),
    enabled: tab !== "alerts", retry: false, refetchInterval: 30_000, refetchIntervalInBackground: false });
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await fn(); await refresh(); } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  };
  const hasNext = tab === "alerts" ? alerts.data?.items.length === 20 : targets.data?.length === 50;
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><h1 className="text-2xl font-semibold">{t("monitoring.title")}</h1>
      <LocalizedLink to="/profile" className="underline">{t("monitoring.settings")}</LocalizedLink></div>
    {settings.error && <Alert tone="danger">{settings.error.message}</Alert>}
    {settings.data && !settings.data.enabled && <Alert><p>{t("monitoring.paused")}</p>
      <Button className="mt-2" disabled={busy} onClick={() => void act(() => monitoringApi.toggle(true))}>{t("monitoring.enable")}</Button></Alert>}
    {settings.data?.enabled && settings.data.next_check_at && Date.now() - new Date(`${settings.data.next_check_at.replace(/Z$/, "")}Z`).getTime() > 180_000
      && <Alert tone="warning">{t("monitoring.delayed")}</Alert>}
    <p className="text-sm text-muted-foreground">{t("monitoring.experimental")}</p>
    <div role="tablist" aria-label={t("monitoring.title")} className="flex gap-2">
      {(["watchlist", "holdings", "alerts"] as const).map((name) => <Button role="tab" aria-selected={tab === name} key={name} variant={tab === name ? "primary" : "secondary"}
        onClick={() => { setParams({ tab: name }); setOffset(0); }}>{t(`monitoring.${name}`)}{name === "alerts" ? ` (${alerts.data?.unread_count ?? 0})` : ""}</Button>)}
    </div>
    {error && <Alert tone="danger">{error}</Alert>}
    {(tab === "alerts" ? alerts.isPending : targets.isPending) && <p>{t("common.loading")}</p>}
    {(tab === "alerts" ? alerts.error : targets.error) && <Alert tone="danger">{(tab === "alerts" ? alerts.error : targets.error)?.message}</Alert>}
    {tab !== "alerts" && targets.data?.length === 0 && <p>{t("monitoring.empty")} <LocalizedLink to="/markets" className="underline">{t("monitoring.findAssets")}</LocalizedLink></p>}
    {tab !== "alerts" && targets.data?.map((target) => <TargetCard key={target.id} target={target} enabled={settings.data?.enabled} forecastsEnabled={settings.data?.forecasts_enabled} nextCheck={settings.data?.next_check_at} trading={Boolean(capabilities.data?.enabled)} busy={busy}
      remove={() => void act(() => monitoringApi.remove(target.id))} />)}
    {tab === "alerts" && alerts.data?.items.length === 0 && <p>{t("monitoring.emptyAlerts")}</p>}
    {tab === "alerts" && alerts.data?.items.map((signal) => <Card key={signal.id} className={params.get("notification") === signal.id ? "ring-2 ring-primary" : undefined}><CardBody className="space-y-2">
      <p className="font-semibold">{notificationTitle(signal, t)}</p>
      <p className="text-sm text-muted-foreground">{signal.payload.exchange} · {t(`monitoring.${signal.kind}`)} · {t(`monitoring.${signal.direction}`)}</p>
      <p>{percent(signal.payload.change_percent)} · {stamp(signal.created_at)}</p>
      {signal.payload.forecast && <p>{t("monitoring.range")}: {price(signal.payload.forecast.lower)} – {price(signal.payload.forecast.upper)} · {signal.payload.forecast.target_date}</p>}
      <p>{t("monitoring.dataAt")}: {stamp(signal.payload.data_at)}</p>
      <div className="flex flex-wrap gap-3">{capabilities.data?.enabled && <TradeAction tradeId={signal.payload.trade_id} exchange={signal.payload.exchange} ticker={signal.payload.ticker} />}
        {!signal.read_at && <Button disabled={busy} variant="secondary" onClick={() => void act(() => monitoringApi.read(signal.id))}>{t("monitoring.markRead")}</Button>}</div>
    </CardBody></Card>)}
    {tab !== "watchlist" && <div className="flex gap-2"><Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - (tab === "alerts" ? 20 : 50)))}>{t("monitoring.previous")}</Button>
      <Button variant="secondary" disabled={!hasNext} onClick={() => setOffset(offset + (tab === "alerts" ? 20 : 50))}>{t("monitoring.next")}</Button></div>}
  </div>;
}

function TradeAction({ tradeId, exchange, ticker }: { tradeId: string | null; exchange: string; ticker: string }) {
  const { t } = useTranslation();
  return <LocalizedLink className={buttonClasses()} to={tradeId ? `/trades?trade=${tradeId}` : `/checkout?${new URLSearchParams({ ticker, exchange })}`}>
    {t(tradeId ? "monitoring.viewPosition" : "monitoring.checkout")}
  </LocalizedLink>;
}

function TargetCard({ target, enabled, forecastsEnabled, nextCheck, trading, busy, remove }: { target: Target; enabled?: boolean; forecastsEnabled?: boolean; nextCheck?: string | null; trading: boolean; busy: boolean; remove: () => void }) {
  const { t } = useTranslation();
  const r = target.result;
  const snapshot = r.snapshot ?? (r.price && r.data_at ? { price: r.price, data_at: r.data_at, status: undefined } : undefined);
  const currentPrice = snapshot?.price;
  const change = currentPrice && target.reference_price
    ? String((Number(currentPrice) / Number(target.reference_price) - 1) * 100) : undefined;
  return <Card><CardBody className="space-y-2">
    <h2 className="font-semibold">{target.ticker} · {target.exchange}{target.trade_id && ` · ${target.trade_id.slice(0, 8)}`}</h2>
    <p>{t("monitoring.status")}: {enabled === undefined ? t("common.loading") : t(`monitoring.statuses.${enabled ? r.status ?? "waitingFirst" : "paused"}`)}</p>
    {snapshot ? <>
      <p>{t(!enabled || r.status !== "ready" ? "monitoring.savedClose" : "monitoring.latest")}: {price(currentPrice)}</p>
      <p>{t("monitoring.reference")}: {target.reference_price ? price(target.reference_price) : t("monitoring.referencePending")}{change !== undefined && ` · ${percent(change)}`}</p>
      {snapshot.status === "stale_data" && <p>{t("monitoring.statuses.stale_data")}</p>}
      <p className="text-xs">{t("monitoring.dataAt")}: {stamp(snapshot.data_at)}</p>
      <p className="text-xs text-muted-foreground">{t("monitoring.candleValuation")}</p>
    </> : <><p>{t("monitoring.noSnapshot")}</p>
      {target.reference_price && <p>{t("monitoring.reference")}: {price(target.reference_price)}</p>}
      {r.preview_status && <p>{t(`monitoring.statuses.${r.preview_status}`)}</p>}</>}
    {enabled === false && <p className="text-sm">{t("monitoring.updatesPaused")}</p>}
    <p>{t("monitoring.forecast")}: {t(`monitoring.statuses.${forecastsEnabled === false ? "disabled" : r.forecast?.status ?? "waiting"}`)}</p>
    {forecastsEnabled !== false && r.forecast?.status === "ready" && <><p>{percent(r.forecast.change_percent)} · {price(r.forecast.price)} · {t("monitoring.range")}: {price(r.forecast.lower)} – {price(r.forecast.upper)} · {r.forecast.target_date}</p>
      <p>{t("monitoring.forecastReference")}: {price(r.forecast.reference_price)} · {r.forecast.reference_date}</p></>}
    {enabled && <p className="text-xs">{t("monitoring.nextCheck")}: {stamp(nextCheck ?? r.next_check_at)}</p>}
    <div className="flex flex-wrap gap-3">{trading && <TradeAction tradeId={target.trade_id} exchange={target.exchange} ticker={target.ticker} />}
      {!target.trade_id && <Button variant="secondary" disabled={busy} onClick={remove}>{t("monitoring.remove")}</Button>}</div>
  </CardBody></Card>;
}
