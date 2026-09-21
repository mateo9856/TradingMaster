/**
 * Live screen — the end-to-end proof: exchange → Kafka → API → browser.
 *
 * History comes from the REST endpoint, then the WebSocket keeps the last
 * candle moving. The raw message panel shows that a Binance candle and a
 * Coinbase candle really do arrive in the same shape, in USD.
 */

import { useEffect, useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";

import { CandleChart } from "@/components/CandleChart";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import { StatTile } from "@/components/StatTile";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/field";
import { useLiveCandles } from "@/hooks/useLiveCandles";
import { ApiError, api } from "@/lib/api";
import { formatChange, formatPrice, formatTimestamp, formatVolume } from "@/lib/format";
import type { Candle, LiveCandle, Market } from "@/lib/types";

const CANDLE_LIMIT = 300;
const DEFAULT_TICKER = "BTC/USD";

export function LivePage() {
  const [ticker, setTicker] = useState<string | null>(null);
  const [interval, setInterval] = useState("1m");
  const [exchange, setExchange] = useState<string | null>(null);
  const [liveCandle, setLiveCandle] = useState<LiveCandle | null>(null);

  const marketsQuery = useQuery({ queryKey: ["markets"], queryFn: api.markets });
  const markets = marketsQuery.data ?? [];
  // Default to Bitcoin — what people look at first — rather than whichever
  // coin happens to sort first alphabetically.
  const market: Market | undefined =
    markets.find((m) => m.ticker === ticker) ??
    markets.find((m) => m.ticker === DEFAULT_TICKER) ??
    markets[0];

  // Settle on a valid selection whenever the market list or the market changes.
  useEffect(() => {
    if (!market) return;
    if (ticker !== market.ticker) setTicker(market.ticker);
    if (!exchange || !market.exchanges.includes(exchange)) setExchange(market.exchanges[0] ?? null);
    if (!market.intervals.includes(interval)) setInterval(market.intervals[0] ?? "1m");
  }, [market, ticker, exchange, interval]);

  const candlesQuery = useQuery({
    queryKey: ["candles", market?.ticker, interval, exchange],
    queryFn: () =>
      api.candles({
        ticker: market!.ticker,
        interval,
        exchange: exchange ?? undefined,
        limit: CANDLE_LIMIT,
      }),
    enabled: Boolean(market && exchange),
    // "No candles yet" is a 404 from this API — a state to show, not to retry.
    retry: (count, error) => !(error instanceof ApiError) && count < 2,
  });

  const live = useLiveCandles({
    ticker: market?.ticker ?? null,
    interval,
    exchange: exchange ?? undefined,
    enabled: Boolean(market && exchange),
    onCandle: setLiveCandle,
  });

  // Latest close per exchange — the cross-exchange comparison the unified feed enables.
  const perExchange = useQueries({
    queries: (market?.exchanges ?? []).map((name) => ({
      queryKey: ["latest", market?.ticker, interval, name],
      queryFn: () => api.candles({ ticker: market!.ticker, interval, exchange: name, limit: 1 }),
      enabled: Boolean(market),
      refetchInterval: 15_000,
      retry: false,
    })),
  });

  const candles: Candle[] = candlesQuery.data ?? [];
  const stats = useMemo(() => {
    if (!candles.length) return null;
    const newest = candles[0];        // REST returns newest first
    const oldest = candles[candles.length - 1];
    const close = liveCandle?.close_price ?? newest.close_price;
    return {
      close,
      change: formatChange(oldest.open_price, close),
      rising: Number(close) >= Number(oldest.open_price),
      volume: liveCandle?.volume ?? newest.volume,
      fxRate: liveCandle?.fx_rate ?? newest.fx_rate,
      sourceTicker: liveCandle?.source_ticker ?? newest.source_ticker,
      timestamp: liveCandle?.timestamp ?? newest.timestamp,
    };
  }, [candles, liveCandle]);

  if (marketsQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading markets…</p>;
  }

  if (marketsQuery.isError) {
    return (
      <Alert tone="danger" title="Cannot reach the API">
        {(marketsQuery.error as Error).message}. Start it with{" "}
        <code className="font-mono">uvicorn app.main:app --reload</code>.
      </Alert>
    );
  }

  if (!markets.length || !market) {
    return (
      <Alert tone="warning" title="No markets configured">
        The database has no enabled exchange with an enabled symbol. Start the API once to seed the
        defaults, or add a market through <code className="font-mono">POST /api/v1/exchanges/…/symbols</code>.
      </Alert>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader
          title={`${market.ticker} · ${interval}`}
          description={
            stats?.sourceTicker && stats.sourceTicker !== market.ticker
              ? `${exchange} trades this as ${stats.sourceTicker}; prices converted to USD`
              : "Prices in USD, exactly as stored"
          }
          actions={<ConnectionBadge status={live.status} error={live.error} count={live.messageCount} />}
        />
        <CardBody className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Market">
            {(id) => (
              <Select
                id={id}
                value={market.ticker}
                onChange={(event) => {
                  setTicker(event.target.value);
                  setLiveCandle(null);
                }}
              >
                {markets.map((option) => (
                  <option key={option.ticker} value={option.ticker}>
                    {option.ticker}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <Field label="Interval">
            {(id) => (
              <Select
                id={id}
                value={interval}
                onChange={(event) => {
                  setInterval(event.target.value);
                  setLiveCandle(null);
                }}
              >
                {market.intervals.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <Field label="Exchange" hint="One exchange at a time — each has its own order book">
            {(id) => (
              <Select
                id={id}
                value={exchange ?? ""}
                onChange={(event) => {
                  setExchange(event.target.value);
                  setLiveCandle(null);
                }}
              >
                {market.exchanges.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <div className="flex items-end">
            <p className="text-xs text-muted-foreground">
              {candles.length} candle{candles.length === 1 ? "" : "s"} loaded
              {stats ? ` · last ${formatTimestamp(stats.timestamp)} UTC` : ""}
            </p>
          </div>
        </CardBody>
      </Card>

      {stats ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile label="Last price" value={`$${formatPrice(stats.close)}`} tone={stats.rising ? "up" : "down"} />
          <StatTile label={`Change (${candles.length} candles)`} value={stats.change} tone={stats.rising ? "up" : "down"} />
          <StatTile label="Volume (last candle)" value={formatVolume(stats.volume)} />
          <StatTile
            label="USD conversion"
            value={stats.fxRate ? formatPrice(stats.fxRate) : "1.00000000"}
            hint={stats.sourceTicker ?? market.ticker}
          />
        </div>
      ) : null}

      <Card>
        <CardHeader title="Price" description={`${exchange} · ${market.ticker} · ${interval}`} />
        <CardBody>
          {candlesQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Loading candles…</p>
          ) : candlesQuery.error instanceof ApiError && candlesQuery.error.isNotFound ? (
            <Alert tone="warning" title="No candles stored yet">
              Nothing has been saved for {market.ticker} {interval} on {exchange}. Check that the producer
              and the Flink job are running — the live stream below still works without them.
            </Alert>
          ) : candlesQuery.isError ? (
            <Alert tone="danger" title="Could not load candles">
              {(candlesQuery.error as Error).message}
            </Alert>
          ) : (
            <CandleChart candles={candles} liveCandle={liveCandle} />
          )}
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Latest price per exchange"
            description="Same coin, same currency, same format — what the unified feed is for"
          />
          <CardBody className="flex flex-col gap-2">
            {(market.exchanges ?? []).map((name, index) => {
              const result = perExchange[index];
              const latest = result?.data?.[0];
              return (
                <div key={name} className="flex items-center justify-between gap-3 text-sm">
                  <span className="font-medium">{name}</span>
                  {latest ? (
                    <span className="tabular text-muted-foreground">
                      ${formatPrice(latest.close_price)}{" "}
                      <span className="text-xs">({formatTimestamp(latest.timestamp, false)} UTC)</span>
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">
                      {result?.isPending ? "loading…" : "no data yet"}
                    </span>
                  )}
                </div>
              );
            })}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Last live message"
            description="Raw WebSocket payload, unchanged"
            actions={liveCandle ? <Badge tone="info">{liveCandle.exchange}</Badge> : null}
          />
          <CardBody>
            {liveCandle ? (
              <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed">
                {JSON.stringify(liveCandle, null, 2)}
              </pre>
            ) : live.status === "error" ? (
              <Alert tone="danger" title="Live stream rejected">
                {live.error}
              </Alert>
            ) : (
              <p className="text-sm text-muted-foreground">
                Waiting for the first message… candles arrive as the exchange publishes them (every few
                seconds for {interval}).
              </p>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
