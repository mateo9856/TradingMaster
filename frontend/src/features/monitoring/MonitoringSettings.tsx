import { useState } from "react";
import { useTranslation } from "react-i18next";
import { monitoringApi, type Settings } from "./api";
import { useMonitoring, useMonitoringSettings } from "./hooks";
import { Alert } from "@/shared/ui/alert";
import { Button } from "@/shared/ui/button";
import { Field, Input, Select } from "@/shared/ui/field";

export function MonitoringSettings() {
  const query = useMonitoringSettings();
  const { t } = useTranslation();
  if (query.isPending) return <p>{t("common.loading")}</p>;
  if (query.error) return <Alert tone="danger">{query.error.message}</Alert>;
  return <SettingsForm initial={query.data} />;
}

function SettingsForm({ initial }: { initial: Settings }) {
  const { t } = useTranslation();
  const { refresh } = useMonitoring();
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  return <form className="flex flex-col gap-3 border-t pt-4" onSubmit={async (event) => {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      const { enabled, upward_percent, downward_percent, check_minutes, horizon_days } = value;
      const saved = await monitoringApi.save({ enabled, upward_percent, downward_percent, check_minutes, horizon_days });
      setValue(saved); await refresh(); setMessage(t("monitoring.saved"));
    } catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  }}>
    <h2 className="font-semibold">{t("monitoring.settings")}</h2>
    <label><input type="checkbox" checked={value.enabled} onChange={(e) => setValue({ ...value, enabled: e.target.checked })} /> {t("monitoring.enabled")}</label>
    {(["upward_percent", "downward_percent"] as const).map((name) => <Field key={name} label={t(`monitoring.${name}`)}>
      {(id) => <Input id={id} type="number" required min="0.0001" max="100" step="0.0001" value={value[name]} onChange={(e) => setValue({ ...value, [name]: e.target.value })} />}
    </Field>)}
    <Field label={t("monitoring.frequency")}>{(id) => <Select id={id} value={value.check_minutes} onChange={(e) => setValue({ ...value, check_minutes: Number(e.target.value) })}>
      {[15, 60, 1440].map((n) => <option key={n} value={n}>{t(`monitoring.frequency_${n}`)}</option>)}
    </Select>}</Field>
    <Field label={t("monitoring.horizon")} hint={t("monitoring.horizonHint")}>{(id) => <Input id={id} type="number" min="1" max="365" step="1" required value={value.horizon_days || ""}
      onChange={(e) => setValue({ ...value, horizon_days: Number(e.target.value) })} />}</Field>
    <p className="text-xs text-muted-foreground">{t("monitoring.experimental")}</p>
    {!initial.forecasts_enabled && <p>{t("monitoring.forecastDisabled")}</p>}
    {message && <p role="status">{message}</p>}
    <Button disabled={busy}>{t("monitoring.save")}</Button>
  </form>;
}
