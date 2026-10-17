/**
 * System screen — is the pipeline actually running? Health plus the handful of
 * Prometheus counters that answer "is data flowing, and is anything degraded".
 */

import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Seo } from "@/components/Seo";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { StatTile } from "@/components/StatTile";
import { api } from "@/lib/api";
import { intlLocale } from "@/lib/i18n";
import { metricSamples, metricTotal, parseMetrics } from "@/lib/metrics";

export function SystemPage() {
  const { t } = useTranslation();
  const count = (value: number) => value.toLocaleString(intlLocale());
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 10_000,
  });

  const metricsQuery = useQuery({
    queryKey: ["metrics"],
    queryFn: async () => parseMetrics(await api.metrics()),
    refetchInterval: 10_000,
    retry: false,
  });

  const samples = metricsQuery.data ?? [];
  const produced = metricTotal(samples, "kafka_messages_produced_total");
  const skipped = metricTotal(samples, "candles_skipped_total");
  const pegFallbacks = metricTotal(samples, "fx_rate_fallback_total");
  const viewers = metricTotal(samples, "websocket_active_connections");
  const reconnects = metricTotal(samples, "kafka_reconnects_total");
  const fxRates = metricSamples(samples, "fx_rate");
  const archiveRuns = metricSamples(samples, "eod_job_runs_total");

  const byExchange = new Map<string, number>();
  for (const sample of metricSamples(samples, "kafka_messages_produced_total")) {
    const exchange = sample.labels.exchange ?? "unknown";
    byExchange.set(exchange, (byExchange.get(exchange) ?? 0) + sample.value);
  }

  return (
    <div className="flex flex-col gap-4">
      <Seo title={t("seo.system_title")} noindex />
      <h1 className="text-2xl font-semibold tracking-tight">{t("nav.system")}</h1>
      <Card>
        <CardHeader
          title={t("system.healthTitle")}
          description={t("system.healthDescription")}
          actions={
            healthQuery.isSuccess ? (
              <Badge tone="success">{t("system.healthy")}</Badge>
            ) : healthQuery.isError ? (
              <Badge tone="danger">{t("system.unreachable")}</Badge>
            ) : (
              <Badge>{t("system.checking")}</Badge>
            )
          }
        />
        <CardBody className="flex flex-wrap gap-4 text-sm text-muted-foreground">
          <a className="underline underline-offset-4 hover:text-foreground" href="/docs" target="_blank" rel="noreferrer">
            {t("system.docs")}
          </a>
          <a className="underline underline-offset-4 hover:text-foreground" href="/redoc" target="_blank" rel="noreferrer">
            {t("system.redoc")}
          </a>
          <a className="underline underline-offset-4 hover:text-foreground" href="/metrics" target="_blank" rel="noreferrer">
            {t("system.rawMetrics")}
          </a>
        </CardBody>
      </Card>

      {metricsQuery.isError ? (
        <Alert tone="warning" title={t("system.metricsUnavailableTitle")}>
          {t("system.metricsUnavailableBody")}
        </Alert>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label={t("system.produced")} value={count(produced)} />
            <StatTile label={t("system.viewers")} value={count(viewers)} />
            <StatTile
              label={t("system.dropped")}
              value={count(skipped)}
              tone={skipped > 0 ? "down" : "neutral"}
              hint={t("system.droppedHint")}
            />
            <StatTile
              label={t("system.pegFallbacks")}
              value={count(pegFallbacks)}
              tone={pegFallbacks > 0 ? "down" : "neutral"}
              hint={t("system.pegFallbacksHint")}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title={t("system.perExchangeTitle")} description={t("system.perExchangeDescription")} />
              <CardBody className="flex flex-col gap-2 text-sm">
                {byExchange.size ? (
                  [...byExchange.entries()].sort().map(([exchange, value]) => (
                    <div key={exchange} className="flex items-center justify-between">
                      <span>{exchange}</span>
                      <span className="tabular text-muted-foreground">{count(value)}</span>
                    </div>
                  ))
                ) : (
                  <p className="text-muted-foreground">{t("system.nothingCollected")}</p>
                )}
                {reconnects > 0 ? (
                  <p className="mt-1 text-xs text-muted-foreground">{t("system.reconnects", { count: reconnects })}</p>
                ) : null}
              </CardBody>
            </Card>

            <Card>
              <CardHeader title={t("system.ratesTitle")} description={t("system.ratesDescription")} />
              <CardBody className="flex flex-col gap-2 text-sm">
                {fxRates.length ? (
                  fxRates.map((sample) => (
                    <div key={sample.labels.quote} className="flex items-center justify-between">
                      <span>1 {sample.labels.quote}</span>
                      {/* Fixed 8 decimals so 1.0 and 0.99972 line up as the same kind of number. */}
                      <span className="tabular text-muted-foreground">${sample.value.toFixed(8)}</span>
                    </div>
                  ))
                ) : (
                  <p className="text-muted-foreground">{t("system.noRate")}</p>
                )}
                {archiveRuns.length ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {t("system.archiveRuns")}{" "}
                    {archiveRuns.map((sample) => `${sample.value} ${sample.labels.status}`).join(", ")}
                  </p>
                ) : null}
              </CardBody>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
