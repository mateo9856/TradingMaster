import { useEffect, useId, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import type { AlertCursor, AlertPage, Signal } from "./api";
import { monitoringApi } from "./api";

/** Start after the current inbox; page through bursts using a stable server cursor. */
export function useNotificationFeed(userId: string, baseline: AlertPage) {
  const session = useId();
  const cursor = useRef<AlertCursor>(baseline.items[0]
    ? { after: baseline.items[0].created_at, after_id: baseline.items[0].id }
    : { after: baseline.checked_at ?? new Date().toISOString() });
  const query = useQuery({
    queryKey: ["monitoring", userId, "notification-feed", session],
    queryFn: async ({ signal }) => {
      let next = cursor.current;
      const items: Signal[] = [];
      // Bound each poll, then resume at the last delivered item on the next one.
      for (let page = 0; page < 5; page++) {
        const batch = await monitoringApi.alertFeed(next, signal);
        items.push(...batch.items);
        const last = batch.items.at(-1);
        if (last) next = { after: last.created_at, after_id: last.id };
        if (batch.items.length < 100) break;
      }
      return { items, cursor: next };
    },
    retry: false, gcTime: 0, refetchInterval: 30_000, refetchIntervalInBackground: false,
  });
  useEffect(() => {
    if (query.data) cursor.current = query.data.cursor;
  }, [query.data]);
  return query;
}
