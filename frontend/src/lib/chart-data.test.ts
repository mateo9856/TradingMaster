import { describe, expect, it } from "vitest";

import { DOWN_COLOR, UP_COLOR, toBar, toChartData, toVolumeBar } from "./chart-data";
import { candle, liveCandle } from "@/test/handlers";

describe("toBar", () => {
  it("converts decimal strings into chart numbers with an epoch time", () => {
    expect(toBar(candle())).toEqual({
      time: Date.UTC(2026, 8, 19, 12, 0, 0) / 1000,
      open: 65000,
      high: 65300,
      low: 64850,
      close: 65200,
    });
  });

  it("works for a live message as well as a stored row", () => {
    expect(toBar(liveCandle()).close).toBe(65350);
  });
});

describe("toVolumeBar", () => {
  it("colours volume by the candle's own direction", () => {
    expect(toVolumeBar(candle({ open_price: "1", close_price: "2" })).color).toBe(`${UP_COLOR}66`);
    expect(toVolumeBar(candle({ open_price: "2", close_price: "1" })).color).toBe(`${DOWN_COLOR}66`);
  });
});

describe("toChartData", () => {
  it("sorts the newest-first API rows into ascending chart order", () => {
    const rows = [
      candle({ id: 3, timestamp: "2026-09-19T12:02:00" }),
      candle({ id: 2, timestamp: "2026-09-19T12:01:00" }),
      candle({ id: 1, timestamp: "2026-09-19T12:00:00" }),
    ];

    const { bars, volume } = toChartData(rows);

    expect(bars.map((bar) => bar.time)).toEqual([...bars.map((bar) => bar.time)].sort((a, b) => a - b));
    expect(bars).toHaveLength(3);
    expect(volume).toHaveLength(3);
  });

  it("keeps the freshest row when a timestamp repeats", () => {
    // Newest first: the developing candle arrives before the older copy.
    const rows = [
      candle({ close_price: "70000.00000000" }),
      candle({ close_price: "65200.00000000" }),
    ];

    const { bars } = toChartData(rows);

    expect(bars).toHaveLength(1);
    expect(bars[0].close).toBe(70000);
  });

  it("has nothing to draw for an empty result", () => {
    expect(toChartData([])).toEqual({ bars: [], volume: [] });
  });
});
