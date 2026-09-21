import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useLiveCandles } from "./useLiveCandles";
import { FakeWebSocket, installFakeWebSocket } from "@/test/fake-websocket";
import { liveCandle } from "@/test/handlers";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("connecting", () => {
  it("opens the unified-ticker WebSocket path with the exchange filter", async () => {
    installFakeWebSocket();

    renderHook(() => useLiveCandles({ ticker: "BTC/USD", interval: "1m", exchange: "binance" }));

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    expect(FakeWebSocket.last.url).toBe(
      `ws://${window.location.host}/api/v1/market/ws/live/BTCUSD?exchange=binance`,
    );
  });

  it("omits the filter when every exchange is wanted", async () => {
    installFakeWebSocket();

    renderHook(() => useLiveCandles({ ticker: "ETH/USD", interval: "1m" }));

    await waitFor(() => expect(FakeWebSocket.last.url).toMatch(/ETHUSD$/));
  });

  it("reports the stream as live once the socket opens", async () => {
    installFakeWebSocket();
    const { result } = renderHook(() => useLiveCandles({ ticker: "BTC/USD", interval: "1m" }));

    expect(result.current.status).toBe("connecting");
    act(() => FakeWebSocket.last.open());

    expect(result.current.status).toBe("live");
  });

  it("opens no socket while disabled", () => {
    installFakeWebSocket();

    const { result } = renderHook(() => useLiveCandles({ ticker: "BTC/USD", interval: "1m", enabled: false }));

    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(result.current.status).toBe("closed");
  });
});

describe("messages", () => {
  it("passes candles of the selected interval to the chart", async () => {
    installFakeWebSocket();
    const onCandle = vi.fn();
    const { result } = renderHook(() =>
      useLiveCandles({ ticker: "BTC/USD", interval: "1m", onCandle }),
    );
    act(() => FakeWebSocket.last.open());

    const candle = liveCandle();
    act(() => FakeWebSocket.last.emit(candle));

    expect(onCandle).toHaveBeenCalledWith(candle);
    expect(result.current.lastMessage).toEqual(candle);
    expect(result.current.messageCount).toBe(1);
  });

  it("keeps other intervals off the chart — one topic carries them all", async () => {
    installFakeWebSocket();
    const onCandle = vi.fn();
    const { result } = renderHook(() =>
      useLiveCandles({ ticker: "BTC/USD", interval: "1m", onCandle }),
    );
    act(() => FakeWebSocket.last.open());

    act(() => FakeWebSocket.last.emit(liveCandle({ interval: "1h" })));

    expect(onCandle).not.toHaveBeenCalled();
    expect(result.current.messageCount).toBe(1); // still shown in the raw feed
  });

  it("survives a malformed frame", async () => {
    installFakeWebSocket();
    const onCandle = vi.fn();
    const { result } = renderHook(() =>
      useLiveCandles({ ticker: "BTC/USD", interval: "1m", onCandle }),
    );
    act(() => FakeWebSocket.last.open());

    act(() => FakeWebSocket.last.emit("not json"));

    expect(onCandle).not.toHaveBeenCalled();
    expect(result.current.status).toBe("live");
    expect(result.current.messageCount).toBe(0);
  });
});

describe("closing", () => {
  it("stops and explains when the API rejects the market (1008)", async () => {
    installFakeWebSocket();
    vi.useFakeTimers();
    const { result } = renderHook(() => useLiveCandles({ ticker: "DOGE/USD", interval: "1m" }));

    act(() => FakeWebSocket.last.serverClose(1008, "Unknown market DOGEUSD"));

    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe("Unknown market DOGEUSD");

    act(() => vi.advanceTimersByTime(30_000));
    expect(FakeWebSocket.instances).toHaveLength(1); // never retried
  });

  it("reconnects after an unexpected drop", async () => {
    installFakeWebSocket();
    vi.useFakeTimers();
    const { result } = renderHook(() => useLiveCandles({ ticker: "BTC/USD", interval: "1m" }));
    act(() => FakeWebSocket.last.open());

    act(() => FakeWebSocket.last.serverClose(1006));
    expect(result.current.status).toBe("closed");

    act(() => vi.advanceTimersByTime(1_000));
    expect(FakeWebSocket.instances).toHaveLength(2);

    act(() => FakeWebSocket.last.open());
    expect(result.current.status).toBe("live");
  });

  it("closes the socket when the component goes away", async () => {
    installFakeWebSocket();
    const { unmount } = renderHook(() => useLiveCandles({ ticker: "BTC/USD", interval: "1m" }));
    const socket = FakeWebSocket.last;

    unmount();

    expect(socket.closed).toBe(true);
  });

  it("starts a new socket and clears the feed when the market changes", async () => {
    installFakeWebSocket();
    const { result, rerender } = renderHook(
      ({ ticker }: { ticker: string }) => useLiveCandles({ ticker, interval: "1m" }),
      { initialProps: { ticker: "BTC/USD" } },
    );
    act(() => FakeWebSocket.last.open());
    act(() => FakeWebSocket.last.emit(liveCandle()));

    rerender({ ticker: "ETH/USD" });

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    expect(FakeWebSocket.last.url).toMatch(/ETHUSD/);
    expect(result.current.lastMessage).toBeNull();
    expect(result.current.messageCount).toBe(0);
  });
});
