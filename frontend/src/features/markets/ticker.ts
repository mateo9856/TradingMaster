/**
 * Ticker spellings.
 *
 * The API accepts any spelling of a USD-equivalent market and resolves it to
 * the unified ticker, but the two transports need different shapes:
 *   REST      /api/v1/market/candles/BTC%2FUSD   (URL-encoded, handled by the client)
 *   WebSocket /api/v1/market/ws/live/BTCUSD      (no slash — it's a path segment)
 */

/** "BTC/USD" → "BTCUSD", for the WebSocket path. */
export function toWsSegment(ticker: string): string {
  const segment = ticker.trim().toUpperCase().replace(/[/\-_]/g, "");
  if (!segment) throw new Error("Ticker must not be empty");
  return segment;
}

/** The coin part of a unified ticker: "BTC/USD" → "BTC". */
export function baseAsset(ticker: string): string {
  return ticker.split("/")[0]?.trim().toUpperCase() ?? ticker;
}
