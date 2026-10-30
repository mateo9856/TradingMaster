import { request, requestData, query } from "@/shared/http";
import type { HistoryCandle } from "./types";
import type { ApiResponse } from "@/shared/types";

export const historyApi = {
  /** Archived candles for a date range (cold storage). */
  history(params: {
    ticker: string;
    date_from: string;
    date_to: string;
    interval?: string;
    exchange?: string;
    limit?: number;
    currency?: string;
  }): Promise<HistoryCandle[]> {
    const { ticker, ...rest } = params;
    return requestData<HistoryCandle[]>(
      `/api/v1/history/${encodeURIComponent(ticker)}${query(rest)}`,
    );
  },

  /** Triggers the end-of-day archive for one date. Requires a logged-in user. */
  triggerArchive(date: string): Promise<ApiResponse<null>> {
    return request<ApiResponse<null>>(`/api/v1/history/archive/${date}`, { method: "POST" });
  },

};
