import type { Candle } from "@/features/markets/types";

export interface HistoryCandle extends Omit<Candle, "id"> {
  id: number;
  trade_date: string;
  archived_at: string;
}

