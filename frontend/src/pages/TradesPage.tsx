import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { LocalizedLink } from "@/components/LocalizedLink";
import { Seo } from "@/components/Seo";
import { TradeConfirmation } from "@/components/TradeConfirmation";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/field";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatExchange } from "@/lib/format";
import { useTradingCapabilities, useTradingWallet } from "@/lib/trading";
import type { Trade, TradingQuote } from "@/lib/trading";

export function TradesPage() {
  const { user, loading } = useAuth();
  const capabilities = useTradingCapabilities();
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-4">
      <Seo title={t("seo.trades_title")} noindex />
      <h1 className="text-2xl font-semibold">{t("trading.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("trading.simulated")}</p>
      {loading || capabilities.isPending ? <p>{t("common.loading")}</p>
        : capabilities.error ? <Alert tone="danger">{capabilities.error.message}</Alert>
        : !capabilities.data?.enabled ? <Alert>{t("trading.disabled")}</Alert>
        : !user ? <LocalizedLink to="/login" className="underline">{t("trading.signIn")}</LocalizedLink>
        : <TradingAccount key={user.id} userId={user.id} />}
    </div>
  );
}

function TradingAccount({ userId }: { userId: string }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const wallet = useTradingWallet(true);
  const [status, setStatus] = useState<"open" | "closed">("open");
  const [offset, setOffset] = useState(0);
  const [amount, setAmount] = useState("1000");
  const topUpKey = useRef<string | null>(null);
  const [preview, setPreview] = useState<{ quote: TradingQuote; key: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const trades = useQuery({
    queryKey: ["trading", userId, "trades", status, offset],
    queryFn: () => api.trades(status, offset), enabled: Boolean(wallet.data),
    retry: false,
    refetchInterval: status === "open" ? 15_000 : false,
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["trading", userId] });
  const act = async (work: () => Promise<void>) => {
    setBusy(true); setError(null); setMessage(null);
    try { await work(); } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  };
  const prepareSell = (trade: Trade) => act(async () => {
    const quote = await api.tradingQuote({ side: "sell", trade_id: trade.id });
    setPreview({ quote, key: crypto.randomUUID() });
  });
  const sell = () => act(async () => {
    if (!preview?.quote.trade_id) return;
    await api.sellTrade(preview.quote.trade_id, preview.quote.id, preview.key);
    setPreview(null); setMessage(t("trading.sold")); await refresh();
  });
  const topUp = () => act(async () => {
    topUpKey.current ??= crypto.randomUUID();
    await api.demoTopUp(amount, topUpKey.current);
    topUpKey.current = null; setMessage(t("trading.funded")); await refresh();
  });
  return (
    <>
      <Card>
        <CardHeader title={t("trading.balance")} description={t("trading.creditHint")} />
        <CardBody className="flex flex-col gap-3">
          <p className="text-xl tabular-nums">{wallet.data?.balance ?? "…"} {t("trading.credits")}</p>
          {wallet.error && <Alert tone="danger">{wallet.error.message}</Alert>}
          <form className="flex max-w-md flex-col gap-3" onSubmit={(event) => { event.preventDefault(); void topUp(); }}>
            <Field label={t("trading.topUpAmount")}>
              {(id) => <Input id={id} required type="number" min="0.00000001" max="1000000000000" step="0.00000001" value={amount} disabled={busy} onChange={(event) => { setAmount(event.target.value); topUpKey.current = null; }} />}
            </Field>
            <Button disabled={busy || !wallet.data}>{t("trading.addCredits")}</Button>
          </form>
          <div className="flex flex-wrap gap-2">
            {["card", "paypal", "bank"].map((method) => <Button key={method} variant="secondary" disabled>{t(`trading.${method}`)} · {t("trading.comingSoon")}</Button>)}
          </div>
        </CardBody>
      </Card>
      {error && <Alert tone="danger">{error}</Alert>}
      {message && <Alert>{message}</Alert>}
      {preview && <TradeConfirmation quote={preview.quote} busy={busy} onConfirm={() => void sell()} onCancel={() => setPreview(null)} />}
      <div className="flex gap-2" aria-label={t("trading.status")}>
        {(["open", "closed"] as const).map((value) => <Button key={value} variant={status === value ? "primary" : "secondary"} onClick={() => { setStatus(value); setOffset(0); }}>{t(`trading.${value}`)}</Button>)}
      </div>
      {trades.isError ? <Alert tone="danger">{trades.error.message}</Alert>
        : trades.isPending ? <p>{t("common.loading")}</p>
        : <>
          {!trades.data.items.length && <p>{t("trading.empty")}</p>}
          <div className="grid gap-3 lg:grid-cols-2">
            {trades.data.items.map((trade) => {
              const pnl = trade.status === "closed" ? trade.realized_pnl : trade.valuation?.unrealized_pnl;
              return <Card key={trade.id}>
                <CardHeader title={`${trade.ticker} · ${formatExchange(trade.exchange)}`} description={new Date(trade.opened_at).toLocaleString()} />
                <CardBody className="flex flex-col gap-2 text-sm tabular-nums">
                  <p>{t("trading.quantity")}: {trade.quantity}</p>
                  <p>{t("trading.cost")}: {trade.cost} {t("trading.credits")}</p>
                  <p>{t("trading.sellValue")}: {(trade.status === "closed" ? trade.proceeds : trade.valuation?.sell_value) ?? "—"} {t("trading.credits")}</p>
                  <p className={pnl && Number(pnl) < 0 ? "text-red-600" : "text-green-600"}>{t(trade.status === "closed" ? "trading.realizedPnl" : "trading.pnl")}: {pnl ?? "—"} {t("trading.credits")}</p>
                  {trade.valuation && <>
                    <p>{t("trading.spread")}: {trade.valuation.spread} USD ({trade.valuation.spread_percent}%)</p>
                    <p>{t("trading.quoteTime")} {trade.valuation.source_at ?? trade.valuation.received_at}</p>
                    {trade.valuation.delayed && <p>{t("trading.delayed")}</p>}
                  </>}
                  {trade.valuation_error && <Alert tone="warning">{t("trading.unavailable")}: {trade.valuation_error}</Alert>}
                  {trade.status === "open" && <Button disabled={busy || Boolean(preview) || !trade.valuation} onClick={() => void prepareSell(trade)}>{t("trading.sell")}</Button>}
                </CardBody>
              </Card>;
            })}
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 10))}>{t("trading.previous")}</Button>
            <Button variant="secondary" disabled={offset + trades.data.limit >= trades.data.total} onClick={() => setOffset(offset + trades.data.limit)}>{t("trading.next")}</Button>
          </div>
        </>}
    </>
  );
}
