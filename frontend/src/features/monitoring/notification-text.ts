import type { TFunction } from "i18next";
import { parseUtc } from "@/shared/format";
import type { Signal } from "./api";

export function notificationTitle(signal: Signal, t: TFunction): string {
  let key: string;
  if (signal.kind === "forecast") {
    key = signal.payload.trade_id
      ? signal.direction === "down" ? "sellOpportunity" : "holdingUpside"
      : signal.direction === "up" ? "buyOpportunity" : "declineForecast";
  } else {
    key = signal.payload.trade_id
      ? signal.direction === "up" ? "profitTarget" : "lossThreshold"
      : signal.direction === "up" ? "priceRise" : "priceFall";
  }
  return t(`notifications.${key}`, { ticker: signal.payload.ticker });
}

export function notificationBody(signal: Signal, t: TFunction): string {
  const amount = Number(signal.payload.change_percent);
  const percent = Number.isFinite(amount) ? `${amount > 0 ? "+" : ""}${amount.toFixed(2)}%` : "—";
  const target = signal.payload.forecast?.target_date;
  return t(signal.kind === "forecast" ? target ? "notifications.forecastBy" : "notifications.forecastChange" : "notifications.observedChange",
    { percent, date: target, exchange: signal.payload.exchange });
}

export function isCurrentNotification(signal: Signal): boolean {
  // Expired forecasts remain in history, but must not become new opportunities.
  const target = signal.payload.forecast?.target_date;
  return !signal.read_at && (signal.kind !== "forecast" || !target
    || parseUtc(`${target}T23:59:59`).getTime() >= Date.now());
}
