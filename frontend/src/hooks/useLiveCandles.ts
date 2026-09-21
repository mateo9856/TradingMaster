/**
 * Live candles over the market WebSocket.
 *
 * ws://…/api/v1/market/ws/live/{TICKER}?exchange=… pushes one unified candle
 * per message. The same window is pushed repeatedly as it develops, so the
 * consumer updates the last bar rather than appending.
 *
 * Close codes that matter:
 *   1008 — the market isn't configured (the API rejects it deliberately)
 *   1011 — server-side error
 * A 1008 is final: reconnecting would be rejected again, so we stop and say why.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { LiveCandle } from "@/lib/types";
import { toWsSegment } from "@/lib/ticker";

export type ConnectionStatus = "connecting" | "live" | "closed" | "error";

export interface LiveCandlesState {
  status: ConnectionStatus;
  error: string | null;
  lastMessage: LiveCandle | null;
  messageCount: number;
}

const POLICY_VIOLATION = 1008;
const RECONNECT_DELAYS_MS = [1_000, 2_000, 5_000, 10_000];

export interface UseLiveCandlesOptions {
  ticker: string | null;
  interval: string;
  exchange?: string;
  /** Called for every message whose interval matches — used to update the chart. */
  onCandle?: (candle: LiveCandle) => void;
  enabled?: boolean;
}

export function useLiveCandles({
  ticker,
  interval,
  exchange,
  onCandle,
  enabled = true,
}: UseLiveCandlesOptions): LiveCandlesState {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [lastMessage, setLastMessage] = useState<LiveCandle | null>(null);
  const [messageCount, setMessageCount] = useState(0);

  // Kept in refs so a new callback identity doesn't tear down the socket.
  const onCandleRef = useRef(onCandle);
  onCandleRef.current = onCandle;
  const intervalRef = useRef(interval);
  intervalRef.current = interval;

  const handleMessage = useCallback((raw: string) => {
    let candle: LiveCandle;
    try {
      candle = JSON.parse(raw) as LiveCandle;
    } catch {
      return; // a malformed frame must not kill the stream
    }
    setLastMessage(candle);
    setMessageCount((count) => count + 1);
    // One topic carries every interval of a market — keep the selected one.
    if (candle.interval === intervalRef.current) onCandleRef.current?.(candle);
  }, []);

  useEffect(() => {
    if (!enabled || !ticker) {
      setStatus("closed");
      return;
    }

    let socket: WebSocket | null = null;
    let retry = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;

    const url = () => {
      const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
      const params = exchange ? `?exchange=${encodeURIComponent(exchange)}` : "";
      return `${scheme}//${window.location.host}/api/v1/market/ws/live/${toWsSegment(ticker)}${params}`;
    };

    const connect = () => {
      if (disposed) return;
      setStatus("connecting");
      socket = new WebSocket(url());

      socket.onopen = () => {
        retry = 0;
        setStatus("live");
        setError(null);
      };

      socket.onmessage = (event: MessageEvent<string>) => handleMessage(event.data);

      socket.onclose = (event: CloseEvent) => {
        if (disposed) return;
        if (event.code === POLICY_VIOLATION) {
          // Deliberate rejection — no enabled market for this ticker.
          setStatus("error");
          setError(event.reason || `No live market for ${ticker}`);
          return;
        }
        setStatus("closed");
        const delay = RECONNECT_DELAYS_MS[Math.min(retry, RECONNECT_DELAYS_MS.length - 1)];
        retry += 1;
        reconnectTimer = setTimeout(connect, delay);
      };

      socket.onerror = () => {
        if (!disposed) setError("Live stream connection problem");
      };
    };

    connect();

    return () => {
      disposed = true;
      clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [ticker, exchange, enabled, handleMessage]);

  // A change of market or interval starts a fresh picture.
  useEffect(() => {
    setLastMessage(null);
    setMessageCount(0);
  }, [ticker, exchange, interval]);

  return { status, error, lastMessage, messageCount };
}
