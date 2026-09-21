import { describe, expect, it } from "vitest";

import {
  changeDirection,
  formatChange,
  formatPrice,
  formatTimestamp,
  formatVolume,
  parseUtc,
  toEpochSeconds,
  toNumber,
  todayUtc,
} from "./format";

describe("toNumber", () => {
  it("parses the feed's 8-decimal strings", () => {
    expect(toNumber("65000.10000000")).toBe(65000.1);
    expect(toNumber("0.00000001")).toBe(1e-8);
    expect(toNumber(42)).toBe(42);
  });

  it.each(["", "abc", "NaN", "Infinity"])("rejects %s", (value) => {
    expect(() => toNumber(value)).toThrow(/Not a numeric value/);
  });
});

describe("formatPrice", () => {
  it("shows fewer decimals for large prices and more for small ones", () => {
    expect(formatPrice("65000.10000000")).toBe("65,000.10");
    expect(formatPrice("3.12345678")).toBe("3.1235");
    expect(formatPrice("0.00001234")).toBe("0.00001234");
  });

  it("throws on non-numeric input rather than rendering NaN", () => {
    expect(() => formatPrice("n/a")).toThrow();
  });
});

describe("formatVolume", () => {
  it("scales the precision to the magnitude", () => {
    expect(formatVolume("3549.92310000")).toBe("3,550");
    expect(formatVolume("15.40000000")).toBe("15.4");
    expect(formatVolume("0.00000001")).toBe("0.00000001");
  });
});

describe("formatChange", () => {
  it("signs the percentage and marks direction", () => {
    expect(formatChange("100.00000000", "101.50000000")).toBe("+1.50%");
    expect(formatChange("100.00000000", "97.00000000")).toBe("-3.00%");
    expect(changeDirection("100", "101")).toBe("up");
    expect(changeDirection("100", "99")).toBe("down");
    expect(changeDirection("100", "100")).toBe("flat");
  });

  it("has no percentage to show when the base is zero", () => {
    expect(formatChange("0", "5")).toBe("—");
  });
});

describe("timestamps", () => {
  it("reads naive API timestamps as UTC, not local time", () => {
    expect(parseUtc("2026-09-19T18:22:00").toISOString()).toBe("2026-09-19T18:22:00.000Z");
    expect(toEpochSeconds("1970-01-01T00:01:00")).toBe(60);
  });

  it("keeps an explicit zone when one is present", () => {
    expect(parseUtc("2026-09-19T18:22:00Z").toISOString()).toBe("2026-09-19T18:22:00.000Z");
  });

  it("formats for tables, with or without seconds", () => {
    expect(formatTimestamp("2026-09-19T18:22:30")).toBe("2026-09-19 18:22:30");
    expect(formatTimestamp("2026-09-19T18:22:30", false)).toBe("2026-09-19 18:22");
  });

  it("rejects an unparseable timestamp", () => {
    expect(() => parseUtc("yesterday")).toThrow(/Not a timestamp/);
  });

  it("offsets dates for the date pickers", () => {
    expect(todayUtc()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    const from = new Date(`${todayUtc(-7)}T00:00:00Z`).getTime();
    const to = new Date(`${todayUtc()}T00:00:00Z`).getTime();
    expect(Math.round((to - from) / 86_400_000)).toBe(7);
  });
});
