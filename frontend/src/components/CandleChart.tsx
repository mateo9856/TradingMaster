/**
 * Candlestick chart (TradingView lightweight-charts).
 *
 * Seeded with history from the REST endpoint and updated in place from the
 * live WebSocket: exchanges re-send the developing candle, so `series.update`
 * rewrites the last bar instead of appending a new one.
 *
 * Colour: teal rise / red fall — validated for colour-vision deficiency
 * (deutan ΔE 11.6 against each other, both ≥3:1 on the dark surface), and
 * direction is also carried by the candle's own geometry, never colour alone.
 */

import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";

import { DOWN_COLOR, UP_COLOR, toBar, toChartData, toVolumeBar } from "@/lib/chart-data";
import type { Candle, LiveCandle } from "@/lib/types";

export interface CandleChartProps {
  candles: Candle[];
  /** Newest live message for the charted market/interval, or null. */
  liveCandle?: LiveCandle | null;
  height?: number;
}

export function CandleChart({ candles, liveCandle, height = 420 }: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const lastBarRef = useRef<CandlestickData<UTCTimestamp> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#9aa4b2",
        fontSize: 11,
        attributionLogo: false,
      },
      // Recessive grid: present enough to read values, never competing with the marks.
      grid: {
        vertLines: { color: "rgba(148, 163, 184, 0.08)" },
        horzLines: { color: "rgba(148, 163, 184, 0.08)" },
      },
      rightPriceScale: { borderColor: "rgba(148, 163, 184, 0.2)" },
      timeScale: { borderColor: "rgba(148, 163, 184, 0.2)", timeVisible: true, secondsVisible: true },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { locale: "en-US" },
      autoSize: true,
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP_COLOR,
      downColor: DOWN_COLOR,
      borderUpColor: UP_COLOR,
      borderDownColor: DOWN_COLOR,
      wickUpColor: UP_COLOR,
      wickDownColor: DOWN_COLOR,
    });

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    // Volume sits in the bottom fifth so it supports the price, not competes with it.
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    chartRef.current = chart;
    seriesRef.current = series;
    volumeRef.current = volume;

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      volumeRef.current = null;
    };
  }, [height]);

  // Seed / reseed from history.
  useEffect(() => {
    const series = seriesRef.current;
    const volume = volumeRef.current;
    if (!series || !volume) return;

    const { bars, volume: volumeBars } = toChartData(candles);
    series.setData(bars);
    volume.setData(volumeBars);
    lastBarRef.current = bars.at(-1) ?? null;
    if (bars.length) chartRef.current?.timeScale().fitContent();
  }, [candles]);

  // Apply live updates to the last bar (or append when a new window opens).
  useEffect(() => {
    const series = seriesRef.current;
    const volume = volumeRef.current;
    if (!series || !volume || !liveCandle) return;

    const bar = toBar(liveCandle);
    const last = lastBarRef.current;
    // Older than what's charted (a late message after a reconnect) — ignore it,
    // lightweight-charts requires non-decreasing times.
    if (last && bar.time < last.time) return;

    series.update(bar);
    volume.update(toVolumeBar(liveCandle));
    lastBarRef.current = bar;
  }, [liveCandle]);

  return <div ref={containerRef} data-testid="candle-chart" style={{ height }} className="w-full" />;
}
