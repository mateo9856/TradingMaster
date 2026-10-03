import { vi } from "vitest";

import type { LiveCandle } from "@/lib/types";

/**
 * Minimal WebSocket stand-in. jsdom's implementation would try to open a real
 * connection, so tests install this instead and drive it by hand.
 */
/** Non-candle frames the live stream sends (see app/routers/market.py:_pump). */
export type ServerFrame = { type: "heartbeat" };

export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static get last(): FakeWebSocket {
    const socket = FakeWebSocket.instances.at(-1);
    if (!socket) throw new Error("No WebSocket was opened");
    return socket;
  }

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  open(): void {
    this.onopen?.(new Event("open"));
  }

  // Not just LiveCandle: the server also sends control frames on this socket —
  // `{"type":"heartbeat"}` when a market is quiet — and tests need to send
  // those too. A raw string covers the malformed-frame case.
  emit(message: LiveCandle | ServerFrame | string): void {
    const data = typeof message === "string" ? message : JSON.stringify(message);
    this.onmessage?.(new MessageEvent("message", { data }));
  }

  serverClose(code = 1006, reason = ""): void {
    this.closed = true;
    this.onclose?.(new CloseEvent("close", { code, reason }));
  }

  close(): void {
    this.closed = true;
  }
}

/** Installs the fake for the current test and clears previous instances. */
export function installFakeWebSocket(): typeof FakeWebSocket {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  return FakeWebSocket;
}
