/**
 * Display currency: which one to show, and how to format money in it.
 *
 * Prices are stored in USD; the API converts them when asked (`?currency=PLN`)
 * with the ECB rate of each candle's date. The UI picks the currency for where
 * the browser is, then lets the user override it:
 *
 *   1. a choice made in this session (the header picker)
 *   2. the signed-in user's saved preference (profile, follows them across devices)
 *   3. the choice remembered in this browser
 *   4. the time zone — where the machine *is* (Europe/Warsaw → PLN), which is
 *      what "run it in Poland, get PLN" means even on an en-US browser
 *   5. the region of the browser languages (pl-PL → PLN, nb → NOK)
 *   6. the server's DEFAULT_CURRENCY, then USD
 *
 * Only currencies the API reports a rate for are ever picked.
 */

import { toNumber } from "./format";
import { intlLocale } from "./i18n";
import { regionForLanguage, regionForTimeZone } from "./region";

export { regionForLanguage, regionForTimeZone, TIMEZONE_REGION } from "./region";

export const BASE_CURRENCY = "USD";
export const STORAGE_KEY = "tradingmaster.currency";

const EURO_REGIONS = [
  "AT", "BE", "BG", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR", "IE", "IT",
  "LT", "LU", "LV", "MT", "NL", "PT", "SI", "SK", "MC", "SM", "VA", "AD", "ME", "XK",
];

/** ISO 3166 region → currency, for the currencies the API can convert to. */
export const REGION_CURRENCY: Record<string, string> = {
  ...Object.fromEntries(EURO_REGIONS.map((region) => [region, "EUR"])),
  PL: "PLN", NO: "NOK", SE: "SEK", DK: "DKK", IS: "ISK", CZ: "CZK", HU: "HUF",
  RO: "RON", CH: "CHF", LI: "CHF", GB: "GBP", TR: "TRY", JP: "JPY", CN: "CNY",
  HK: "HKD", KR: "KRW", SG: "SGD", IN: "INR", ID: "IDR", MY: "MYR", PH: "PHP",
  TH: "THB", IL: "ILS", ZA: "ZAR", AU: "AUD", NZ: "NZD", CA: "CAD", MX: "MXN",
  BR: "BRL", US: "USD",
};

export interface DetectionInput {
  supported: readonly string[];
  sessionChoice?: string | null;
  profile?: string | null;
  stored?: string | null;
  timeZone?: string;
  languages?: readonly string[];
  serverDefault?: string | null;
}

/** The currency to show, following the order in the header of this file. */
export function detectCurrency(input: DetectionInput): string {
  const supported = new Set(input.supported);
  const pick = (code: string | null | undefined) => {
    const upper = code?.toUpperCase();
    return upper && supported.has(upper) ? upper : null;
  };
  const fromRegion = (region: string | null) => (region ? pick(REGION_CURRENCY[region]) : null);

  const explicit = pick(input.sessionChoice) ?? pick(input.profile) ?? pick(input.stored);
  if (explicit) return explicit;

  const fromZone = fromRegion(regionForTimeZone(input.timeZone));
  if (fromZone) return fromZone;

  for (const language of input.languages ?? []) {
    const fromLanguage = fromRegion(regionForLanguage(language));
    if (fromLanguage) return fromLanguage;
  }

  return pick(input.serverDefault) ?? BASE_CURRENCY;
}

/** What the browser says about where it is. */
export function browserEnvironment(): { timeZone?: string; languages: readonly string[] } {
  let timeZone: string | undefined;
  try {
    timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    timeZone = undefined;
  }
  const languages = navigator.languages?.length ? navigator.languages : [navigator.language].filter(Boolean);
  return { timeZone, languages };
}

/** localStorage can throw (private mode, blocked storage) — never let that break the page. */
export function readStoredCurrency(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeCurrency(code: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, code);
  } catch {
    // not remembered in this browser — the session choice still applies
  }
}

/**
 * Money in `currency` for display, in the UI language's locale: "65 200,00 zł",
 * "$65,200.00". Keeps formatPrice's adaptive precision so SHIB at 0.00001234
 * stays meaningful.
 */
export function formatMoney(value: string | number, currency: string, locale: string = intlLocale()): string {
  const amount = toNumber(value);
  const decimals = amount >= 1000 ? 2 : amount >= 1 ? 4 : 8;
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(amount);
  } catch {
    return `${amount.toFixed(decimals)} ${currency}`;
  }
}

/** The market as the reader sees it: "BTC/USD" shown in PLN is "BTC/PLN". */
export function displayTicker(ticker: string, currency: string): string {
  const base = ticker.split("/")[0] ?? ticker;
  return `${base}/${currency}`;
}
