import { describe, expect, it } from "vitest";

import { metricSamples, metricTotal, parseMetrics } from "./metrics";

const EXPOSITION = `
# HELP kafka_messages_produced_total Number of candle messages produced to Kafka
# TYPE kafka_messages_produced_total counter
kafka_messages_produced_total{exchange="binance",ticker="BTC/USD",interval="1m"} 120.0
kafka_messages_produced_total{exchange="kraken",ticker="BTC/USD",interval="1m"} 80.0
fx_rate{quote="USDT"} 0.9997
websocket_active_connections{endpoint="live_candles"} 2.0
malformed line without a value
`;

describe("parseMetrics", () => {
  it("reads samples with their labels and skips comments", () => {
    const samples = parseMetrics(EXPOSITION);

    expect(samples).toHaveLength(4);
    expect(samples[0]).toEqual({
      name: "kafka_messages_produced_total",
      labels: { exchange: "binance", ticker: "BTC/USD", interval: "1m" },
      value: 120,
    });
  });

  it("returns nothing for empty or non-metric text", () => {
    expect(parseMetrics("")).toEqual([]);
    expect(parseMetrics("# only comments\n")).toEqual([]);
  });
});

describe("metricTotal", () => {
  it("sums every label combination", () => {
    expect(metricTotal(parseMetrics(EXPOSITION), "kafka_messages_produced")).toBe(200);
    expect(metricTotal(parseMetrics(EXPOSITION), "kafka_messages_produced_total")).toBe(200);
  });

  it("is zero for a metric the API never emitted", () => {
    expect(metricTotal(parseMetrics(EXPOSITION), "candles_skipped")).toBe(0);
  });
});

describe("metricSamples", () => {
  it("returns one entry per label set", () => {
    expect(metricSamples(parseMetrics(EXPOSITION), "fx_rate")).toEqual([
      { name: "fx_rate", labels: { quote: "USDT" }, value: 0.9997 },
    ]);
  });
});
