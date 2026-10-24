/**
 * The unified feed sends prices and volumes as exact 8-decimal strings
 * ("65000.10000000"). These helpers convert them for charts and shorten them
 * for display without ever re-formatting through a lossy float first. Numbers
 * are formatted in the UI language's locale (src/lib/i18n.ts).
 */

import { intlLocale } from "./i18n";

const EXCHANGE_NAMES = new Map([
  ["binance", "Binance"],
  ["kraken", "Kraken"],
  ["coinbase", "Coinbase"],
  ["yahoo", "Yahoo Finance"],
]);

/** Exchange label for display; keep the original ID in requests and stored data. */
export function formatExchange(exchange: string): string {
  return EXCHANGE_NAMES.get(exchange.toLowerCase()) ?? exchange.charAt(0).toUpperCase() + exchange.slice(1);
}

/** Cash display only. Decimal-string arithmetic keeps large balances exact. */
export function formatCash(value: string | null | undefined): string {
  if (value == null) return "—";
  const match = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(value.trim());
  if (!match) return "—";
  const negative = match[1] === "-";
  const whole = match[2] ?? "0";
  const fraction = match[3] ?? match[4] ?? "";
  const exponent = Number(match[5] ?? 0);
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 100) return "—";
  const digits = whole + fraction;
  const point = whole.length + exponent;
  const integer = point <= 0 ? "0" : digits.slice(0, point).padEnd(point, "0");
  const decimals = point < 0 ? "0".repeat(-point) + digits : digits.slice(point);
  const nonzero = /[1-9]/.test(digits);
  if (BigInt(integer) === 0n && decimals.slice(0, 2).padEnd(2, "0") === "00" && nonzero) {
    return negative ? "-<0.01" : "<0.01";
  }
  let cents = BigInt(integer) * 100n + BigInt(decimals.slice(0, 2).padEnd(2, "0"));
  if ((decimals[2] ?? "0") >= "5") cents += 1n;
  return `${negative && cents !== 0n ? "-" : ""}${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`;
}

/** Decimal string (or number) → number, for charting and maths. NaN-safe: throws instead. */
export function toNumber(value: string | number): number {
  // Number("") is 0 — an empty price must fail loudly, not render as zero.
  if (typeof value === "string" && value.trim() === "") {
    throw new Error("Not a numeric value: empty string");
  }
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`Not a numeric value: ${JSON.stringify(value)}`);
  return parsed;
}

/**
 * Price for display: keeps enough decimals to stay meaningful for cheap coins
 * (SHIB at 0.00001234) without showing eight zeros on BTC.
 */
export function formatPrice(value: string | number, locale: string = intlLocale()): string {
  const amount = toNumber(value);
  const decimals = amount >= 1000 ? 2 : amount >= 1 ? 4 : 8;
  return amount.toLocaleString(locale, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Volume in base-currency units, compact for the wide range across coins. */
export function formatVolume(value: string | number, locale: string = intlLocale()): string {
  const amount = toNumber(value);
  if (amount >= 1000) return amount.toLocaleString(locale, { maximumFractionDigits: 0 });
  if (amount >= 1) return amount.toLocaleString(locale, { maximumFractionDigits: 3 });
  return amount.toLocaleString(locale, { maximumFractionDigits: 8 });
}

/** Signed percentage change between two prices, e.g. "+1.24%". */
export function formatChange(from: string | number, to: string | number, locale: string = intlLocale()): string {
  const start = toNumber(from);
  const end = toNumber(to);
  if (start === 0) return "—";
  const pct = ((end - start) / start) * 100;
  const number = Math.abs(pct).toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${pct >= 0 ? "+" : "-"}${number}%`;
}

export function changeDirection(from: string | number, to: string | number): "up" | "down" | "flat" {
  const delta = toNumber(to) - toNumber(from);
  return delta > 0 ? "up" : delta < 0 ? "down" : "flat";
}

/**
 * API timestamps are naive UTC ("2026-09-19T18:22:00"). JavaScript would read
 * them as local time, so the Z is added before parsing.
 */
export function parseUtc(timestamp: string): Date {
  const iso = /[zZ]|[+-]\d{2}:\d{2}$/.test(timestamp) ? timestamp : `${timestamp}Z`;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) throw new Error(`Not a timestamp: ${timestamp}`);
  return date;
}

/** Seconds since epoch — what lightweight-charts expects on its time axis. */
export function toEpochSeconds(timestamp: string): number {
  return Math.floor(parseUtc(timestamp).getTime() / 1000);
}

/** Short UTC label for tables and tooltips. */
export function formatTimestamp(timestamp: string, withSeconds = true): string {
  const date = parseUtc(timestamp);
  const pad = (n: number) => String(n).padStart(2, "0");
  const time = `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}${
    withSeconds ? `:${pad(date.getUTCSeconds())}` : ""
  }`;
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${time}`;
}

/** Today (UTC) as YYYY-MM-DD, for date inputs. */
export function todayUtc(offsetDays = 0): string {
  const date = new Date(Date.now() + offsetDays * 86_400_000);
  return date.toISOString().slice(0, 10);
}
