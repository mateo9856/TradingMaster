/**
 * The unified feed sends prices and volumes as exact 8-decimal strings
 * ("65000.10000000"). These helpers convert them for charts and shorten them
 * for display without ever re-formatting through a lossy float first.
 */

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
export function formatPrice(value: string | number): string {
  const amount = toNumber(value);
  const decimals = amount >= 1000 ? 2 : amount >= 1 ? 4 : 8;
  return amount.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Volume in base-currency units, compact for the wide range across coins. */
export function formatVolume(value: string | number): string {
  const amount = toNumber(value);
  if (amount >= 1000) return amount.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (amount >= 1) return amount.toLocaleString("en-US", { maximumFractionDigits: 3 });
  return amount.toLocaleString("en-US", { maximumFractionDigits: 8 });
}

/** Signed percentage change between two prices, e.g. "+1.24%". */
export function formatChange(from: string | number, to: string | number): string {
  const start = toNumber(from);
  const end = toNumber(to);
  if (start === 0) return "—";
  const pct = ((end - start) / start) * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
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
