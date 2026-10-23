/**
 * Live screen — the end-to-end proof: exchange → Kafka → API → browser.
 *
 * Every market has its own page, /markets/{slug} (e.g. /markets/bitcoin-btc,
 * /pl/markets/orlen-pkn-wa), which says what the instrument is — its name,
 * type, category or sector, and listing — before the numbers. "/" shows
 * Bitcoin. History comes from the REST endpoint, then the WebSocket keeps the
 * last candle moving. The raw message panel shows that a Binance candle and a
 * Coinbase candle really do arrive in the same shape — in USD as stored, or
 * converted by the API into the display currency (header picker).
 */

import { useEffect, useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import { CandleChart } from "@/components/CandleChart";
import { PurchasePanel } from "@/components/PurchasePanel";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import { LocalizedLink, useLocalizedPath } from "@/components/LocalizedLink";
import { Seo } from "@/components/Seo";
import { StatTile } from "@/components/StatTile";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/field";
import { useLanguage } from "@/hooks/useLanguage";
import { useLiveCandles } from "@/hooks/useLiveCandles";
import { ApiError, api } from "@/lib/api";
import { BASE_CURRENCY, displayTicker, formatMoney } from "@/lib/currency";
import { useCurrency } from "@/lib/currency-context";
import { formatChange, formatExchange, formatPrice, formatTimestamp, formatVolume } from "@/lib/format";
import { marketName, marketSlug, marketSymbol } from "@/lib/market";
import type { AssetClass, Candle, LiveCandle, Market } from "@/lib/types";

const CANDLE_LIMIT = 300;
const DEFAULT_TICKER = "BTC/USD";
const ASSET_GROUPS: AssetClass[] = ["crypto", "stock"];

export function LivePage() {
  const { t } = useTranslation();
  const language = useLanguage();
  const localize = useLocalizedPath();
  const navigate = useNavigate();
  const { slug } = useParams();
  const [interval, setInterval] = useState("1m");
  const [exchange, setExchange] = useState<string | null>(null);
  const [liveCandle, setLiveCandle] = useState<LiveCandle | null>(null);
  const { currency, ready: currencyReady } = useCurrency();

  // A candle in the old currency must not be drawn on a chart in the new one.
  useEffect(() => setLiveCandle(null), [currency]);

  const marketsQuery = useQuery({ queryKey: ["markets", language], queryFn: () => api.markets(language) });
  const markets = marketsQuery.data ?? [];
  // A market page shows its market; "/" defaults to Bitcoin — what people look
  // at first — rather than whichever coin happens to sort first.
  const market: Market | undefined = slug
    ? markets.find((m) => marketSlug(m) === slug)
    : markets.find((m) => m.ticker === DEFAULT_TICKER) ?? markets[0];

  // Settle on a valid selection whenever the market changes.
  useEffect(() => {
    if (!market) return;
    if (!exchange || !market.exchanges.includes(exchange)) setExchange(market.exchanges[0] ?? null);
    if (!market.intervals.includes(interval)) setInterval(market.intervals[0] ?? "1m");
  }, [market, exchange, interval]);

  const candlesQuery = useQuery({
    queryKey: ["candles", market?.ticker, interval, exchange, currency],
    queryFn: () =>
      api.candles({
        ticker: market!.ticker,
        interval,
        exchange: exchange ?? undefined,
        limit: CANDLE_LIMIT,
        currency,
      }),
    enabled: Boolean(market && exchange && currencyReady),
    // "No candles yet" is a 404 from this API — a state to show, not to retry.
    retry: (count, error) => !(error instanceof ApiError) && count < 2,
  });

  const live = useLiveCandles({
    ticker: market?.ticker ?? null,
    interval,
    exchange: exchange ?? undefined,
    currency,
    enabled: Boolean(market && exchange && currencyReady),
    onCandle: setLiveCandle,
  });

  // Latest close per exchange — the cross-exchange comparison the unified feed enables.
  const perExchange = useQueries({
    queries: (market?.exchanges ?? []).map((name) => ({
      queryKey: ["latest", market?.ticker, interval, name, currency],
      queryFn: () => api.candles({ ticker: market!.ticker, interval, exchange: name, limit: 1, currency }),
      enabled: Boolean(market && currencyReady),
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
      currencyRate: liveCandle?.currency_rate ?? newest.currency_rate ?? null,
      rateDate: liveCandle?.rate_date ?? newest.rate_date ?? null,
      sourceTicker: liveCandle?.source_ticker ?? newest.source_ticker,
      timestamp: liveCandle?.timestamp ?? newest.timestamp,
    };
  }, [candles, liveCandle]);

  if (marketsQuery.isPending) {
    return <p className="text-sm text-muted-foreground">{t("live.loadingMarkets")}</p>;
  }

  if (marketsQuery.isError) {
    return (
      <Alert tone="danger" title={t("live.apiDownTitle")}>
        {t("live.apiDownBody", { message: (marketsQuery.error as Error).message })}{" "}
        <code className="font-mono">uvicorn app.main:app --reload</code>.
      </Alert>
    );
  }

  if (!markets.length) {
    return (
      <Alert tone="warning" title={t("live.noMarketsTitle")}>
        {t("live.noMarketsBody")} <code className="font-mono">POST /api/v1/exchanges/…/symbols</code>.
      </Alert>
    );
  }

  if (!market) {
    // An address that names no market — say so (and keep it out of search results).
    return (
      <>
        <Seo title={t("seo.not_found_title")} noindex />
        <Alert tone="warning" title={t("live.marketNotFoundTitle")}>
          {t("live.marketNotFoundBody")}{" "}
          <LocalizedLink to="/markets" className="underline underline-offset-4">
            {t("common.allMarkets")}
          </LocalizedLink>
        </Alert>
      </>
    );
  }

  const name = marketName(market);
  const symbol = marketSymbol(market);
  const shownTicker = displayTicker(market.ticker, currency);
  const isStock = market.asset_class === "stock";
  const conversion =
    currency === BASE_CURRENCY
      ? stats?.sourceTicker && stats.sourceTicker !== market.ticker
        ? t("live.conversionNative", { exchange: formatExchange(exchange ?? ""), source: stats.sourceTicker })
        : t("live.conversionStored")
      : stats?.rateDate
        ? t("live.conversionDisplayDate", { currency, date: stats.rateDate })
        : t("live.conversionDisplay", { currency });

  const pageTitle = slug ? market.page_title ?? `${name} (${symbol}) | TradingMaster` : t("seo.home_title");
  const pageDescription = slug ? market.page_description ?? market.description : t("seo.home_description");
  const origin = window.location.origin;

  return (
    <div className="flex flex-col gap-4">
      <Seo
        title={pageTitle}
        description={pageDescription}
        jsonLd={
          slug
            ? {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                itemListElement: [
                  { "@type": "ListItem", position: 1, name: t("nav.live"), item: origin + localize("/") },
                  { "@type": "ListItem", position: 2, name: t("nav.markets"), item: origin + localize("/markets") },
                  { "@type": "ListItem", position: 3, name, item: origin + localize(`/markets/${marketSlug(market)}`) },
                ],
              }
            : undefined
        }
      />

      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {name} <span className="text-muted-foreground">({symbol})</span>
          </h1>
          {market.asset_class_label ? (
            <Badge tone={isStock ? "info" : "neutral"}>{market.asset_class_label}</Badge>
          ) : null}
          {market.category_label ? <Badge>{market.category_label}</Badge> : null}
          {market.venue_label ? <Badge>{market.venue_label}</Badge> : null}
        </div>
        {market.description ? <p className="max-w-3xl text-sm text-muted-foreground">{market.description}</p> : null}
      </header>

      <Card>
        <CardHeader
          title={`${shownTicker} · ${interval}`}
          description={isStock ? `${conversion} · ${t("live.stockDelay")}` : conversion}
          actions={<ConnectionBadge status={live.status} error={live.error} count={live.messageCount} />}
        />
        <CardBody className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label={t("live.market")}>
            {(id) => (
              <Select
                id={id}
                value={market.ticker}
                onChange={(event) => {
                  const next = markets.find((m) => m.ticker === event.target.value);
                  if (!next) return;
                  setLiveCandle(null);
                  navigate(localize(`/markets/${marketSlug(next)}`));
                }}
              >
                {ASSET_GROUPS.map((assetClass) => {
                  const options = markets.filter((m) => (m.asset_class ?? "crypto") === assetClass);
                  return options.length ? (
                    <optgroup key={assetClass} label={t(`common.assetGroups.${assetClass}`)}>
                      {options.map((option) => (
                        <option key={option.ticker} value={option.ticker}>
                          {marketName(option)} — {displayTicker(option.ticker, currency)}
                        </option>
                      ))}
                    </optgroup>
                  ) : null;
                })}
              </Select>
            )}
          </Field>

          <Field label={t("live.interval")}>
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

          <Field label={t("live.exchange")} hint={t("live.exchangeHint")}>
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
                    {formatExchange(option)}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <div className="flex items-end">
            <p className="text-xs text-muted-foreground">
              {t("live.candlesLoaded", { count: candles.length })}
              {stats ? ` · ${t("live.lastAt", { time: formatTimestamp(stats.timestamp) })}` : ""}
            </p>
          </div>
        </CardBody>
      </Card>

      {stats ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile label={t("live.lastPrice")} value={formatMoney(stats.close, currency)} tone={stats.rising ? "up" : "down"} />
          <StatTile
            label={t("live.change", { count: candles.length })}
            value={stats.change}
            tone={stats.rising ? "up" : "down"}
          />
          <StatTile label={t("live.volumeLast")} value={formatVolume(stats.volume)} />
          {currency === BASE_CURRENCY || !stats.currencyRate ? (
            <StatTile
              label={t("live.usdConversion")}
              value={stats.fxRate ? formatPrice(stats.fxRate) : "1.00000000"}
              hint={stats.sourceTicker ?? market.ticker}
            />
          ) : (
            <StatTile
              label={t("live.currencyRate", { currency })}
              value={`1 USD = ${formatPrice(stats.currencyRate)} ${currency}`}
              hint={stats.rateDate ? t("live.referenceRate", { date: stats.rateDate }) : undefined}
            />
          )}
        </div>
      ) : null}

      <Card>
        <CardHeader title={t("live.price")} description={`${formatExchange(exchange ?? "")} · ${shownTicker} · ${interval}`} />
        <CardBody>
          {candlesQuery.isPending ? (
            <p className="text-sm text-muted-foreground">{t("live.loadingCandles")}</p>
          ) : candlesQuery.error instanceof ApiError && candlesQuery.error.isNotFound ? (
            <Alert tone="warning" title={t("live.noCandlesTitle")}>
              {t("live.noCandlesBody", { market: shownTicker, interval, exchange: formatExchange(exchange ?? "") })}
            </Alert>
          ) : candlesQuery.isError ? (
            <Alert tone="danger" title={t("live.candlesErrorTitle")}>
              {(candlesQuery.error as Error).message}
            </Alert>
          ) : (
            <CandleChart candles={candles} liveCandle={liveCandle} />
          )}
        </CardBody>
      </Card>

      {exchange && <PurchasePanel ticker={market.ticker} exchange={exchange} />}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={t("live.perExchangeTitle")} description={t("live.perExchangeDescription")} />
          <CardBody className="flex flex-col gap-2">
            {(market.exchanges ?? []).map((exchangeName, index) => {
              const result = perExchange[index];
              const latest = result?.data?.[0];
              return (
                <div key={exchangeName} className="flex items-center justify-between gap-3 text-sm">
                  <span className="font-medium">{formatExchange(exchangeName)}</span>
                  {latest ? (
                    <span className="tabular text-muted-foreground">
                      {formatMoney(latest.close_price, currency)}{" "}
                      <span className="text-xs">({formatTimestamp(latest.timestamp, false)} UTC)</span>
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">
                      {result?.isPending ? t("live.loadingShort") : t("live.noDataYet")}
                    </span>
                  )}
                </div>
              );
            })}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title={t("live.lastMessageTitle")}
            description={t("live.lastMessageDescription")}
            actions={liveCandle ? <Badge tone="info">{formatExchange(liveCandle.exchange)}</Badge> : null}
          />
          <CardBody>
            {liveCandle ? (
              <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed">
                {JSON.stringify(liveCandle, null, 2)}
              </pre>
            ) : live.status === "error" ? (
              <Alert tone="danger" title={t("live.streamRejected")}>
                {live.error}
              </Alert>
            ) : (
              <p className="text-sm text-muted-foreground">{t("live.waiting", { interval })}</p>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
