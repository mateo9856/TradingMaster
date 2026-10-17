import { describe, expect, it } from "vitest";

import {
  detectLanguage,
  intlLocale,
  languageAutonym,
  languageFromTag,
  localizedPath,
  splitLanguage,
} from "./i18n";

describe("detectLanguage", () => {
  it("speaks Polish on a machine in Poland, even with an English browser", () => {
    expect(detectLanguage({ languages: ["en-US", "en"], timeZone: "Europe/Warsaw" })).toBe("pl");
  });

  it("prefers a supported non-English browser language over the location", () => {
    expect(detectLanguage({ languages: ["de-DE"], timeZone: "Europe/Warsaw" })).toBe("de");
    expect(detectLanguage({ languages: ["nb-NO"], timeZone: "UTC" })).toBe("no");
  });

  it.each([
    ["Europe/Oslo", "no"], ["Europe/Berlin", "de"], ["Europe/Vienna", "de"], ["Europe/Paris", "fr"],
    ["Europe/Rome", "it"], ["Europe/Madrid", "es"], ["America/Mexico_City", "es"],
    ["America/New_York", "en"], ["Asia/Tokyo", "en"],
  ])("uses the %s time zone → %s", (timeZone, expected) => {
    expect(detectLanguage({ languages: ["en-US"], timeZone })).toBe(expected);
  });

  it("follows a remembered choice above everything", () => {
    expect(detectLanguage({ stored: "en", languages: ["pl-PL"], timeZone: "Europe/Warsaw" })).toBe("en");
    expect(detectLanguage({ stored: "xx", languages: ["fr"], timeZone: "UTC" })).toBe("fr");
  });

  it("falls back to English for unsupported languages", () => {
    expect(detectLanguage({ languages: ["ja-JP", "pt-BR"], timeZone: "UTC" })).toBe("en");
  });
});

describe("tags and locales", () => {
  it.each([["nb-NO", "no"], ["nn", "no"], ["no", "no"], ["PL", "pl"], ["es-419", "es"], ["pt", null]])(
    "%s → %s",
    (tag, expected) => expect(languageFromTag(tag)).toBe(expected),
  );

  it("formats Norwegian as Bokmål", () => {
    expect(intlLocale("no")).toBe("nb");
    expect(intlLocale("pl")).toBe("pl");
  });

  it("names each language in itself", () => {
    expect(languageAutonym("pl")).toBe("Polski");
    expect(languageAutonym("de")).toBe("Deutsch");
    expect(languageAutonym("es")).toBe("Español");
  });
});

describe("paths", () => {
  it.each([
    ["en", "/markets/bitcoin-btc", "/markets/bitcoin-btc"],
    ["pl", "/markets/bitcoin-btc", "/pl/markets/bitcoin-btc"],
    ["pl", "/", "/pl"],
    ["en", "/", "/"],
  ] as const)("localizedPath(%s, %s) = %s", (language, path, expected) => {
    expect(localizedPath(language, path)).toBe(expected);
  });

  it.each([
    ["/pl/markets/x", "pl", "/markets/x"],
    ["/pl", "pl", "/"],
    ["/markets/x", "en", "/markets/x"],
    ["/", "en", "/"],
    ["/xx/markets", "en", "/xx/markets"],
  ])("splitLanguage(%s)", (pathname, language, path) => {
    expect(splitLanguage(pathname)).toEqual({ language, path });
  });
});
