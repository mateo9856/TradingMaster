import { afterEach, describe, expect, it } from "vitest";

import {
  STORAGE_KEY,
  browserEnvironment,
  detectCurrency,
  displayTicker,
  formatMoney,
  readStoredCurrency,
  regionForLanguage,
  regionForTimeZone,
  storeCurrency,
} from "./currency";

const SUPPORTED = ["USD", "EUR", "PLN", "NOK", "SEK", "GBP", "AUD"];

describe("detectCurrency", () => {
  it("picks PLN on a Polish machine even with an English browser", () => {
    expect(detectCurrency({ supported: SUPPORTED, timeZone: "Europe/Warsaw", languages: ["en-US"] })).toBe("PLN");
  });

  it.each([
    ["Europe/Oslo", "NOK"],
    ["Europe/Berlin", "EUR"],
    ["Europe/Sofia", "EUR"],          // Bulgaria uses the euro since 2026
    ["Europe/London", "GBP"],
    ["Australia/Sydney", "AUD"],
    ["America/New_York", "USD"],
  ])("maps the %s time zone to %s", (timeZone, expected) => {
    expect(detectCurrency({ supported: SUPPORTED, timeZone, languages: [] })).toBe(expected);
  });

  it("falls back to the browser language when the time zone says nothing", () => {
    expect(detectCurrency({ supported: SUPPORTED, timeZone: "UTC", languages: ["pl-PL", "en"] })).toBe("PLN");
    expect(detectCurrency({ supported: SUPPORTED, timeZone: "UTC", languages: ["nb"] })).toBe("NOK");
    expect(detectCurrency({ supported: SUPPORTED, timeZone: "UTC", languages: ["sv"] })).toBe("SEK");
  });

  it("follows an explicit choice: session, then profile, then this browser", () => {
    const base = { supported: SUPPORTED, timeZone: "Europe/Warsaw", languages: ["pl-PL"] };

    expect(detectCurrency({ ...base, stored: "EUR" })).toBe("EUR");
    expect(detectCurrency({ ...base, stored: "EUR", profile: "NOK" })).toBe("NOK");
    expect(detectCurrency({ ...base, stored: "EUR", profile: "NOK", sessionChoice: "GBP" })).toBe("GBP");
  });

  it("never picks a currency the API has no rate for", () => {
    // Before the ECB rates load the API offers USD only.
    expect(detectCurrency({ supported: ["USD"], timeZone: "Europe/Warsaw", stored: "PLN" })).toBe("USD");
    expect(detectCurrency({ supported: SUPPORTED, timeZone: "Asia/Tokyo", languages: ["ja-JP"] })).toBe("USD");
  });

  it("uses the server default when nothing else identifies a currency", () => {
    expect(detectCurrency({ supported: SUPPORTED, timeZone: "UTC", languages: [], serverDefault: "EUR" })).toBe("EUR");
  });
});

describe("regions", () => {
  it("reads the region from a language tag, adding the likely one for a bare language", () => {
    expect(regionForLanguage("pl-PL")).toBe("PL");
    expect(regionForLanguage("pl")).toBe("PL");
    expect(regionForLanguage("not a tag!")).toBeNull();
  });

  it("knows time zones only for the regions it maps", () => {
    expect(regionForTimeZone("Europe/Warsaw")).toBe("PL");
    expect(regionForTimeZone("Asia/Dubai")).toBeNull();
    expect(regionForTimeZone(undefined)).toBeNull();
  });
});

describe("browser environment", () => {
  const original = process.env.TZ;
  afterEach(() => {
    process.env.TZ = original;
  });

  it("reads the machine's time zone", () => {
    process.env.TZ = "Europe/Warsaw";
    expect(browserEnvironment().timeZone).toBe("Europe/Warsaw");
  });

  it("remembers the choice, and survives storage that throws", () => {
    storeCurrency("NOK");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("NOK");
    expect(readStoredCurrency()).toBe("NOK");
  });
});

describe("formatting", () => {
  it("formats money in the currency and the locale", () => {
    expect(formatMoney("65200.00000000", "USD", "en-US")).toBe("$65,200.00");
    expect(formatMoney("255047.69", "PLN", "pl-PL")).toMatch(/^255\s047,69\szł$/);
    expect(formatMoney("0.00001234", "EUR", "en-US")).toBe("€0.00001234");
  });

  it("shows the market in the display currency", () => {
    expect(displayTicker("BTC/USD", "PLN")).toBe("BTC/PLN");
    expect(displayTicker("PKN.WA/USD", "PLN")).toBe("PKN.WA/PLN");
  });
});
