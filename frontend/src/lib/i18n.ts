/**
 * UI translations (i18next) and the language rules.
 *
 * Seven languages: English (the base, bundled) plus Polish, German, French,
 * Norwegian, Italian and Spanish, each a lazily loaded chunk. Text *about*
 * instruments (category, sector, description) comes from the API in the
 * requested language (`?lang=`) — only the UI's own words live in
 * src/locales.
 *
 * Every language has its own URLs: English is unprefixed (/markets/bitcoin-btc),
 * the others carry a prefix (/pl/markets/bitcoin-btc). That is what lets a
 * search engine index each language — crawlers send no location and no
 * language preference — and the server writes matching hreflang links
 * (app/seo.py).
 *
 * Which language a first-time visitor sees, in order:
 *   1. a language they chose before (remembered in this browser)
 *   2. a supported non-English browser language (de-DE → de)
 *   3. the language of the country the machine is in, from its time zone
 *      (Europe/Warsaw → pl) — so "run it in Poland, get Polish" holds even on
 *      an English browser, the same rule the display currency follows
 *   4. English
 */

import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "@/locales/en.json";
import { regionForTimeZone } from "./region";

export const SUPPORTED_LANGUAGES = ["en", "pl", "de", "fr", "no", "it", "es"] as const;
export type Language = (typeof SUPPORTED_LANGUAGES)[number];
export const DEFAULT_LANGUAGE: Language = "en";
export const LANGUAGE_STORAGE_KEY = "tradingmaster.language";

type Catalogue = Record<string, unknown>;

const LOADERS: Record<Exclude<Language, "en">, () => Promise<{ default: Catalogue }>> = {
  pl: () => import("@/locales/pl.json"),
  de: () => import("@/locales/de.json"),
  fr: () => import("@/locales/fr.json"),
  no: () => import("@/locales/no.json"),
  it: () => import("@/locales/it.json"),
  es: () => import("@/locales/es.json"),
};

/** Country → language, for the countries whose language the UI speaks. */
const REGION_LANGUAGE: Record<string, Language> = {
  PL: "pl",
  DE: "de", AT: "de", LI: "de",
  FR: "fr", MC: "fr", LU: "fr",
  NO: "no",
  IT: "it", SM: "it", VA: "it",
  ES: "es", MX: "es", AR: "es", CO: "es", CL: "es", PE: "es",
  US: "en", GB: "en", IE: "en", AU: "en", NZ: "en", CA: "en",
};

i18n.use(initReactI18next).init({
  resources: { en: { translation: en } },
  lng: DEFAULT_LANGUAGE,
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: [...SUPPORTED_LANGUAGES],
  interpolation: { escapeValue: false }, // React escapes already
  returnNull: false,
});

export function isLanguage(value: unknown): value is Language {
  return typeof value === "string" && (SUPPORTED_LANGUAGES as readonly string[]).includes(value);
}

/** "nb-NO" / "nn" / "no" → "no"; "pt-BR" → null. */
export function languageFromTag(tag: string): Language | null {
  const base = tag.trim().toLowerCase().split(/[-_]/)[0];
  const normalized = base === "nb" || base === "nn" ? "no" : base;
  return isLanguage(normalized) ? normalized : null;
}

export interface LanguageDetectionInput {
  stored?: string | null;
  languages?: readonly string[];
  timeZone?: string;
}

export function detectLanguage({ stored, languages = [], timeZone }: LanguageDetectionInput): Language {
  if (isLanguage(stored)) return stored;
  for (const tag of languages) {
    const language = languageFromTag(tag);
    if (language && language !== DEFAULT_LANGUAGE) return language;
  }
  const region = regionForTimeZone(timeZone);
  if (region && REGION_LANGUAGE[region]) return REGION_LANGUAGE[region];
  return DEFAULT_LANGUAGE;
}

export function readStoredLanguage(): string | null {
  try {
    return localStorage.getItem(LANGUAGE_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeLanguage(language: Language): void {
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // not remembered — the URL still carries the choice
  }
}

/** Loads a language's catalogue (once) and switches to it. */
export async function activateLanguage(language: Language): Promise<void> {
  if (language !== "en" && !i18n.hasResourceBundle(language, "translation")) {
    const catalogue = await LOADERS[language]();
    i18n.addResourceBundle(language, "translation", catalogue.default, true, true);
  }
  if (i18n.language !== language) await i18n.changeLanguage(language);
}

/** BCP 47 locale for Intl formatting. Norwegian is formatted as Bokmål. */
export function intlLocale(language: string = i18n.language): string {
  return language === "no" ? "nb" : language || DEFAULT_LANGUAGE;
}

/** ("pl", "/markets/x") → "/pl/markets/x"; English is unprefixed. */
export function localizedPath(language: Language, path: string): string {
  const clean = path.startsWith("/") ? path : `/${path}`;
  if (language === DEFAULT_LANGUAGE) return clean;
  return clean === "/" ? `/${language}` : `/${language}${clean}`;
}

/** "/pl/markets/x" → { language: "pl", path: "/markets/x" }; unprefixed paths are English. */
export function splitLanguage(pathname: string): { language: Language; path: string } {
  const [, first = "", ...rest] = pathname.split("/");
  if (isLanguage(first) && first !== DEFAULT_LANGUAGE) {
    return { language: first, path: `/${rest.join("/")}` };
  }
  return { language: DEFAULT_LANGUAGE, path: pathname || "/" };
}

/** The language's own name, capitalised: "polski", "Deutsch", "norsk" → "Polski", "Deutsch", "Norsk". */
export function languageAutonym(language: Language): string {
  try {
    const name = new Intl.DisplayNames([intlLocale(language)], { type: "language" }).of(intlLocale(language));
    if (name) return name.charAt(0).toLocaleUpperCase(intlLocale(language)) + name.slice(1);
  } catch {
    // fall through
  }
  return language.toUpperCase();
}

export default i18n;
