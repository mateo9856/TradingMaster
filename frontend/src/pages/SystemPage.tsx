/**
 * System screen — is the pipeline actually running? Health plus the handful of
 * Prometheus counters that answer "is data flowing, and is anything degraded".
 */

import { useQuery } from "@tanstack/react-query";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { StatTile } from "@/components/StatTile";
import { api } from "@/lib/api";
import { metricSamples, metricTotal, parseMetrics } from "@/lib/metrics";

export function SystemPage() {
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
      <Card>
        <CardHeader
          title="Service health"
          description="Polled every 10 seconds"
          actions={
            healthQuery.isSuccess ? (
              <Badge tone="success">API healthy</Badge>
            ) : healthQuery.isError ? (
              <Badge tone="danger">API unreachable</Badge>
            ) : (
              <Badge>Checking…</Badge>
            )
          }
        />
        <CardBody className="flex flex-wrap gap-4 text-sm text-muted-foreground">
          <a className="underline underline-offset-4 hover:text-foreground" href="/docs" target="_blank" rel="noreferrer">
            OpenAPI docs (/docs)
          </a>
          <a className="underline underline-offset-4 hover:text-foreground" href="/redoc" target="_blank" rel="noreferrer">
            ReDoc (/redoc)
          </a>
          <a className="underline underline-offset-4 hover:text-foreground" href="/metrics" target="_blank" rel="noreferrer">
            Raw metrics (/metrics)
          </a>
        </CardBody>
      </Card>

      {metricsQuery.isError ? (
        <Alert tone="warning" title="Metrics unavailable">
          The API is running without Prometheus metrics, or they couldn't be fetched.
        </Alert>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Candles produced to Kafka" value={produced.toLocaleString("en-US")} />
            <StatTile label="Live stream viewers" value={viewers.toLocaleString("en-US")} />
            <StatTile
              label="Candles dropped"
              value={skipped.toLocaleString("en-US")}
              tone={skipped > 0 ? "down" : "neutral"}
              hint="Could not be converted to the unified format"
            />
            <StatTile
              label="USD peg fallbacks"
              value={pegFallbacks.toLocaleString("en-US")}
              tone={pegFallbacks > 0 ? "down" : "neutral"}
              hint="Conversions made without a fresh FX rate"
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title="Collected per exchange" description="Messages published since the producer started" />
              <CardBody className="flex flex-col gap-2 text-sm">
                {byExchange.size ? (
                  [...byExchange.entries()].sort().map(([exchange, value]) => (
                    <div key={exchange} className="flex items-center justify-between">
                      <span>{exchange}</span>
                      <span className="tabular text-muted-foreground">{value.toLocaleString("en-US")}</span>
                    </div>
                  ))
                ) : (
                  <p className="text-muted-foreground">
                    Nothing collected yet — is the producer running? (It starts with the API.)
                  </p>
                )}
                {reconnects > 0 ? (
                  <p className="mt-1 text-xs text-muted-foreground">{reconnects} exchange reconnect(s)</p>
                ) : null}
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="USD conversion rates" description="Live stablecoin rates used by the unified feed" />
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
                  <p className="text-muted-foreground">No live rate yet — conversions use the 1:1 peg.</p>
                )}
                {archiveRuns.length ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Archive runs:{" "}
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
