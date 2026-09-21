/**
 * Candle rows → lightweight-charts series data.
 *
 * The REST endpoint returns newest first, while the chart needs ascending,
 * gap-free, strictly increasing times. Rows for the same second (an exchange
 * re-sending a developing candle) collapse to the newest one.
 */

import type { CandlestickData, HistogramData, UTCTimestamp } from "lightweight-charts";

import { toEpochSeconds, toNumber } from "./format";
import type { Candle, LiveCandle } from "./types";

export const UP_COLOR = "#26a69a";
export const DOWN_COLOR = "#ef5350";

type AnyCandle = Candle | LiveCandle;

export function toBar(candle: AnyCandle): CandlestickData<UTCTimestamp> {
  return {
    time: toEpochSeconds(candle.timestamp) as UTCTimestamp,
    open: toNumber(candle.open_price),
    high: toNumber(candle.high_price),
    low: toNumber(candle.low_price),
    close: toNumber(candle.close_price),
  };
}

export function toVolumeBar(candle: AnyCandle): HistogramData<UTCTimestamp> {
  const rising = toNumber(candle.close_price) >= toNumber(candle.open_price);
  return {
    time: toEpochSeconds(candle.timestamp) as UTCTimestamp,
    value: toNumber(candle.volume),
    color: rising ? `${UP_COLOR}66` : `${DOWN_COLOR}66`,
  };
}

/** Ascending, de-duplicated bars — safe to hand straight to `series.setData`. */
export function toChartData(candles: AnyCandle[]): {
  bars: CandlestickData<UTCTimestamp>[];
  volume: HistogramData<UTCTimestamp>[];
} {
  const byTime = new Map<number, AnyCandle>();
  for (const candle of candles) {
    const time = toEpochSeconds(candle.timestamp);
    const existing = byTime.get(time);
    // Later row wins: REST is newest-first, so the first one seen is the freshest.
    if (!existing) byTime.set(time, candle);
  }
  const ordered = [...byTime.entries()].sort(([a], [b]) => a - b).map(([, candle]) => candle);
  return { bars: ordered.map(toBar), volume: ordered.map(toVolumeBar) };
}
