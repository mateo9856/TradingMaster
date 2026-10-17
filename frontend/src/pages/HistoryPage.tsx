/**
 * History screen — archived candles (cold storage) plus the manual end-of-day
 * archive trigger, which is the one destructive-ish action in the MVP and
 * therefore requires a logged-in user.
 */

import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Seo } from "@/components/Seo";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/field";
import { ApiError, api } from "@/lib/api";
import { useLanguage } from "@/hooks/useLanguage";
import { useAuth } from "@/lib/auth";
import { BASE_CURRENCY, formatMoney } from "@/lib/currency";
import { useCurrency } from "@/lib/currency-context";
import { formatTimestamp, formatVolume, todayUtc } from "@/lib/format";
import { marketName } from "@/lib/market";
import { INTERVALS } from "@/lib/types";

interface Search {
  ticker: string;
  date_from: string;
  date_to: string;
  interval: string;
  exchange: string;
  limit: number;
}

export function HistoryPage() {
  const { user } = useAuth();
  const { t } = useTranslation();
  const language = useLanguage();
  const { currency, ready: currencyReady } = useCurrency();
  const marketsQuery = useQuery({ queryKey: ["markets", language], queryFn: () => api.markets(language) });
  const markets = marketsQuery.data ?? [];

  const [form, setForm] = useState<Search>({
    ticker: "BTC/USD",
    date_from: todayUtc(-7),
    date_to: todayUtc(),
    interval: "1m",
    exchange: "",
    limit: 200,
  });
  const [search, setSearch] = useState<Search | null>(null);
  const [archiveDate, setArchiveDate] = useState(todayUtc(-1));

  const historyQuery = useQuery({
    queryKey: ["history", search, currency],
    queryFn: () =>
      api.history({
        currency,
        ticker: search!.ticker,
        date_from: search!.date_from,
        date_to: search!.date_to,
        interval: search!.interval,
        exchange: search!.exchange || undefined,
        limit: search!.limit,
      }),
    enabled: search !== null && currencyReady,
    retry: (count, error) => !(error instanceof ApiError) && count < 2,
  });

  const archive = useMutation({
    mutationFn: (date: string) => api.triggerArchive(date),
  });

  const rows = historyQuery.data ?? [];
  const error = historyQuery.error;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSearch({ ...form });
  };

  return (
    <div className="flex flex-col gap-4">
      <Seo title={t("seo.history_title")} description={t("seo.history_description")} />
      <h1 className="text-2xl font-semibold tracking-tight">{t("nav.history")}</h1>
      <Card>
        <CardHeader title={t("history.title")} description={t("history.description")} />
        <CardBody>
          <form onSubmit={submit} className="grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-6">
            <Field label={t("history.market")} className="lg:col-span-2">
              {(id) => (
                <Input
                  id={id}
                  list="known-markets"
                  value={form.ticker}
                  onChange={(event) => setForm({ ...form, ticker: event.target.value })}
                  placeholder="BTC/USD"
                />
              )}
            </Field>
            <datalist id="known-markets">
              {markets.map((market) => (
                <option key={market.ticker} value={market.ticker} label={marketName(market)} />
              ))}
            </datalist>

            <Field label={t("history.from")}>
              {(id) => (
                <Input
                  id={id}
                  type="date"
                  value={form.date_from}
                  onChange={(event) => setForm({ ...form, date_from: event.target.value })}
                />
              )}
            </Field>
            <Field label={t("history.to")}>
              {(id) => (
                <Input
                  id={id}
                  type="date"
                  value={form.date_to}
                  onChange={(event) => setForm({ ...form, date_to: event.target.value })}
                />
              )}
            </Field>
            <Field label={t("history.interval")}>
              {(id) => (
                <Select
                  id={id}
                  value={form.interval}
                  onChange={(event) => setForm({ ...form, interval: event.target.value })}
                >
                  {INTERVALS.map((interval) => (
                    <option key={interval} value={interval}>
                      {interval}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t("history.exchange")}>
              {(id) => (
                <Select
                  id={id}
                  value={form.exchange}
                  onChange={(event) => setForm({ ...form, exchange: event.target.value })}
                >
                  <option value="">{t("history.all")}</option>
                  {[...new Set(markets.flatMap((market) => market.exchanges))].sort().map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>

            <Button type="submit" className="sm:col-span-2 lg:col-span-1">
              {t("history.search")}
            </Button>
          </form>

          <div className="mt-4">
            {historyQuery.isFetching ? (
              <p className="text-sm text-muted-foreground">{t("history.searching")}</p>
            ) : error instanceof ApiError && error.isNotFound ? (
              <Alert tone="warning" title={t("history.noneTitle")}>
                {t("history.noneBody")}
              </Alert>
            ) : error instanceof ApiError && error.isValidation ? (
              <Alert tone="danger" title={t("history.unsupportedTitle")}>
                {error.message}
              </Alert>
            ) : error ? (
              <Alert tone="danger" title={t("history.failedTitle")}>
                {(error as Error).message}
              </Alert>
            ) : rows.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <tr className="border-b border-border">
                      <th className="py-2 pr-3 font-medium">{t("history.timestamp")}</th>
                      <th className="py-2 pr-3 font-medium">{t("history.exchange")}</th>
                      <th className="py-2 pr-3 font-medium">{t("history.source")}</th>
                      <th className="py-2 pr-3 text-right font-medium">{t("history.open", { currency })}</th>
                      <th className="py-2 pr-3 text-right font-medium">{t("history.high", { currency })}</th>
                      <th className="py-2 pr-3 text-right font-medium">{t("history.low", { currency })}</th>
                      <th className="py-2 pr-3 text-right font-medium">{t("history.close", { currency })}</th>
                      <th className="py-2 text-right font-medium">{t("history.volume")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.id} className="border-b border-border/60">
                        <td className="tabular py-1.5 pr-3">{formatTimestamp(row.timestamp)}</td>
                        <td className="py-1.5 pr-3">{row.exchange}</td>
                        <td className="py-1.5 pr-3 text-muted-foreground">{row.source_ticker ?? "—"}</td>
                        <td className="tabular py-1.5 pr-3 text-right">{formatMoney(row.open_price, currency)}</td>
                        <td className="tabular py-1.5 pr-3 text-right">{formatMoney(row.high_price, currency)}</td>
                        <td className="tabular py-1.5 pr-3 text-right">{formatMoney(row.low_price, currency)}</td>
                        <td className="tabular py-1.5 pr-3 text-right">{formatMoney(row.close_price, currency)}</td>
                        <td className="tabular py-1.5 text-right">{formatVolume(row.volume)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-xs text-muted-foreground">
                  {t("history.rows", { count: rows.length, limit: search?.limit })}
                  {currency !== BASE_CURRENCY ? ` · ${t("history.converted", { currency })}` : ""}
                </p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">{t("history.prompt")}</p>
            )}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t("history.archiveTitle")} description={t("history.archiveDescription")} />
        <CardBody className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label={t("history.date")}>
              {(id) => (
                <Input
                  id={id}
                  type="date"
                  value={archiveDate}
                  onChange={(event) => setArchiveDate(event.target.value)}
                />
              )}
            </Field>
            <Button
              onClick={() => archive.mutate(archiveDate)}
              disabled={!user || archive.isPending}
              title={user ? undefined : t("history.signInToRun")}
            >
              {archive.isPending ? t("history.starting") : t("history.runArchive")}
            </Button>
          </div>

          {!user ? (
            <Alert tone="info">{t("history.publicNote")}</Alert>
          ) : null}
          {archive.isSuccess ? (
            <Alert tone="success" title={t("history.archiveStarted")}>
              {archive.data?.message ?? t("history.archiving", { date: archiveDate })}
            </Alert>
          ) : null}
          {archive.isError ? (
            <Alert tone="danger" title={t("history.archiveFailed")}>
              {(archive.error as Error).message}
            </Alert>
          ) : null}
        </CardBody>
      </Card>
    </div>
  );
}
