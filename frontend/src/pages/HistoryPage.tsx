/**
 * History screen — archived candles (cold storage) plus the manual end-of-day
 * archive trigger, which is the one destructive-ish action in the MVP and
 * therefore requires a logged-in user.
 */

import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/field";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatPrice, formatTimestamp, formatVolume, todayUtc } from "@/lib/format";
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
  const marketsQuery = useQuery({ queryKey: ["markets"], queryFn: api.markets });
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
    queryKey: ["history", search],
    queryFn: () =>
      api.history({
        ticker: search!.ticker,
        date_from: search!.date_from,
        date_to: search!.date_to,
        interval: search!.interval,
        exchange: search!.exchange || undefined,
        limit: search!.limit,
      }),
    enabled: search !== null,
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
      <Card>
        <CardHeader
          title="Archived candles"
          description="Cold storage (candles_history) — written nightly by the end-of-day job"
        />
        <CardBody>
          <form onSubmit={submit} className="grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-6">
            <Field label="Market" className="lg:col-span-2">
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
                <option key={market.ticker} value={market.ticker} />
              ))}
            </datalist>

            <Field label="From">
              {(id) => (
                <Input
                  id={id}
                  type="date"
                  value={form.date_from}
                  onChange={(event) => setForm({ ...form, date_from: event.target.value })}
                />
              )}
            </Field>
            <Field label="To">
              {(id) => (
                <Input
                  id={id}
                  type="date"
                  value={form.date_to}
                  onChange={(event) => setForm({ ...form, date_to: event.target.value })}
                />
              )}
            </Field>
            <Field label="Interval">
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
            <Field label="Exchange">
              {(id) => (
                <Select
                  id={id}
                  value={form.exchange}
                  onChange={(event) => setForm({ ...form, exchange: event.target.value })}
                >
                  <option value="">All</option>
                  {[...new Set(markets.flatMap((market) => market.exchanges))].sort().map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>

            <Button type="submit" className="sm:col-span-2 lg:col-span-1">
              Search
            </Button>
          </form>

          <div className="mt-4">
            {historyQuery.isFetching ? (
              <p className="text-sm text-muted-foreground">Searching…</p>
            ) : error instanceof ApiError && error.isNotFound ? (
              <Alert tone="warning" title="No archived candles for that range">
                History is written by the nightly job, so today's data usually isn't there yet. Try an
                earlier date, or run the archive below.
              </Alert>
            ) : error instanceof ApiError && error.isValidation ? (
              <Alert tone="danger" title="Unsupported market">
                {error.message}
              </Alert>
            ) : error ? (
              <Alert tone="danger" title="Search failed">
                {(error as Error).message}
              </Alert>
            ) : rows.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <tr className="border-b border-border">
                      <th className="py-2 pr-3 font-medium">Timestamp (UTC)</th>
                      <th className="py-2 pr-3 font-medium">Exchange</th>
                      <th className="py-2 pr-3 font-medium">Source</th>
                      <th className="py-2 pr-3 text-right font-medium">Open</th>
                      <th className="py-2 pr-3 text-right font-medium">High</th>
                      <th className="py-2 pr-3 text-right font-medium">Low</th>
                      <th className="py-2 pr-3 text-right font-medium">Close</th>
                      <th className="py-2 text-right font-medium">Volume</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.id} className="border-b border-border/60">
                        <td className="tabular py-1.5 pr-3">{formatTimestamp(row.timestamp)}</td>
                        <td className="py-1.5 pr-3">{row.exchange}</td>
                        <td className="py-1.5 pr-3 text-muted-foreground">{row.source_ticker ?? "—"}</td>
                        <td className="tabular py-1.5 pr-3 text-right">{formatPrice(row.open_price)}</td>
                        <td className="tabular py-1.5 pr-3 text-right">{formatPrice(row.high_price)}</td>
                        <td className="tabular py-1.5 pr-3 text-right">{formatPrice(row.low_price)}</td>
                        <td className="tabular py-1.5 pr-3 text-right">{formatPrice(row.close_price)}</td>
                        <td className="tabular py-1.5 text-right">{formatVolume(row.volume)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-xs text-muted-foreground">
                  {rows.length} row{rows.length === 1 ? "" : "s"} (limit {search?.limit})
                </p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Choose a market and date range, then search.</p>
            )}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Run the end-of-day archive"
          description="Copies a day's candles into history and exports Parquet — normally a nightly job"
        />
        <CardBody className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Date (UTC)">
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
              title={user ? undefined : "Sign in to run the archive"}
            >
              {archive.isPending ? "Starting…" : "Run archive"}
            </Button>
          </div>

          {!user ? (
            <Alert tone="info">
              Reading data is public; changing anything needs an account. Sign in to run the archive.
            </Alert>
          ) : null}
          {archive.isSuccess ? (
            <Alert tone="success" title="Archive started">
              {archive.data?.message ?? `Archiving ${archiveDate} in the background.`}
            </Alert>
          ) : null}
          {archive.isError ? (
            <Alert tone="danger" title="Could not start the archive">
              {(archive.error as Error).message}
            </Alert>
          ) : null}
        </CardBody>
      </Card>
    </div>
  );
}
