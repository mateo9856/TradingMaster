import { describe, expect, it } from "vitest";

import { baseAsset, toWsSegment } from "./ticker";

describe("toWsSegment", () => {
  it.each([
    ["BTC/USD", "BTCUSD"],
    ["BTC/USDT", "BTCUSDT"],
    ["btc-usd", "BTCUSD"],
    ["  eth/usd  ", "ETHUSD"],
  ])("%s → %s", (input, expected) => {
    expect(toWsSegment(input)).toBe(expected);
  });

  it("rejects an empty ticker instead of opening a bad socket", () => {
    expect(() => toWsSegment("   ")).toThrow(/must not be empty/);
  });
});

describe("baseAsset", () => {
  it("takes the coin out of a unified ticker", () => {
    expect(baseAsset("BTC/USD")).toBe("BTC");
    expect(baseAsset("SHIB/USD")).toBe("SHIB");
  });
});
