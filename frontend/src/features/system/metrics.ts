/**
 * Minimal parser for the Prometheus exposition format served at /metrics.
 *
 * Only what the System screen shows: a metric's samples with their labels, and
 * a total across all label combinations. Not a general-purpose parser — it
 * ignores HELP/TYPE lines, histograms buckets and exemplars.
 */

export interface MetricSample {
  name: string;
  labels: Record<string, string>;
  value: number;
}

const LINE = /^(?<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?<labels>[^}]*)\})?\s+(?<value>[^\s]+)/;

export function parseMetrics(text: string): MetricSample[] {
  const samples: MetricSample[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const match = LINE.exec(trimmed);
    if (!match?.groups) continue;

    const value = Number(match.groups.value);
    if (!Number.isFinite(value)) continue;

    const labels: Record<string, string> = {};
    for (const pair of match.groups.labels?.split(",") ?? []) {
      const [key, ...rest] = pair.split("=");
      if (!key || rest.length === 0) continue;
      labels[key.trim()] = rest.join("=").trim().replace(/^"|"$/g, "");
    }
    samples.push({ name: match.groups.name, labels, value });
  }
  return samples;
}

/** Sum of every sample of `name` (prometheus_client suffixes counters with _total). */
export function metricTotal(samples: MetricSample[], name: string): number {
  return samples
    .filter((sample) => sample.name === name || sample.name === `${name}_total`)
    .reduce((total, sample) => total + sample.value, 0);
}

/** Samples of one metric, for a per-label breakdown (e.g. fx_rate by quote). */
export function metricSamples(samples: MetricSample[], name: string): MetricSample[] {
  return samples.filter((sample) => sample.name === name);
}
