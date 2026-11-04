import { requestData } from "@/shared/http";

export interface Settings {
  enabled: boolean;
  upward_percent: string;
  downward_percent: string;
  check_minutes: number;
  horizon_days: number;
  forecasts_enabled: boolean;
  next_check_at: string | null;
}
export interface Forecast {
  status: string;
  change_percent?: string;
  price?: string;
  lower?: string;
  upper?: string;
  target_date?: string;
  reference_price?: string;
  reference_date?: string;
}
export interface Target {
  id: string;
  exchange: string;
  ticker: string;
  trade_id: string | null;
  reference_price: string | null;
  created_at: string;
  result: { status?: string; price?: string; change_percent?: string; data_at?: string;
    evaluated_at?: string; next_check_at?: string; forecast?: Forecast; preview_status?: string;
    snapshot?: { price: string; data_at: string; interval?: string; status?: string } };
}
export interface Signal {
  id: string;
  kind: "observed" | "forecast";
  direction: "up" | "down";
  created_at: string;
  read_at: string | null;
  payload: { exchange: string; ticker: string; trade_id: string | null; change_percent: string;
    threshold_percent: string; data_at: string; forecast: Forecast | null };
}
export interface AlertPage { items: Signal[]; unread_count: number; checked_at?: string }
export interface AlertCursor { after: string; after_id?: string }
const root = "/api/v1/monitoring";
const json = (method: string, body: unknown) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const monitoringApi = {
  settings: () => requestData<Settings>(`${root}/settings`),
  toggle: (enabled: boolean) => requestData<Settings>(`${root}/settings`, json("PATCH", { enabled })),
  save: (body: Pick<Settings, "enabled" | "upward_percent" | "downward_percent" | "check_minutes" | "horizon_days">) => requestData<Settings>(`${root}/settings`, json("PUT", body)),
  watchlist: () => requestData<Target[]>(`${root}/watchlist`),
  watch: (exchange: string, ticker: string, enableMonitoring = false) => requestData<Target>(`${root}/watchlist`, json("POST", { exchange, ticker, enable_monitoring: enableMonitoring })),
  remove: (id: string) => requestData(`${root}/watchlist/${id}`, { method: "DELETE" }),
  holdings: (offset = 0) => requestData<Target[]>(`${root}/holdings?offset=${offset}`),
  alerts: (offset = 0) => requestData<AlertPage>(`${root}/alerts?offset=${offset}`),
  alertFeed: (cursor: AlertCursor, signal?: AbortSignal) => requestData<AlertPage>(`${root}/alerts?${new URLSearchParams({
    ...cursor, limit: "100",
  })}`, { signal }),
  read: (id: string) => requestData(`${root}/alerts/${id}/read`, { method: "PATCH" }),
};
