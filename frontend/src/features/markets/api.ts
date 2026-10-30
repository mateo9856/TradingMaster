import { requestData, query } from "@/shared/http";
import type { Candle, Market } from "./types";

export const marketsApi = {
  /** Markets currently collected, one entry per unified ticker, described in `lang`. */
  markets(lang?: string): Promise<Market[]> {
    return requestData<Market[]>(`/api/v1/market/markets${query({ lang })}`);
  },

  /**
   * Recent candles, newest first. Callers that chart them sort ascending —
   * see `toChartData` in ./chart-data.
   */
  candles(params: {
    ticker: string;
    interval: string;
    exchange?: string;
    limit?: number;
    /** Prices in this currency (ECB rate of each candle's date); USD when omitted. */
    currency?: string;
  }): Promise<Candle[]> {
    const { ticker, ...rest } = params;
    return requestData<Candle[]>(
      `/api/v1/market/candles/${encodeURIComponent(ticker)}${query(rest)}`,
    );
  },

};
