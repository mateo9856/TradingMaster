import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { LocalizedLink } from "@/components/LocalizedLink";
import { TradeConfirmation } from "@/components/TradeConfirmation";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/field";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useTradingCapabilities, useTradingWallet } from "@/lib/trading";
import type { TradingQuote } from "@/lib/trading";

export function PurchasePanel({ ticker, exchange }: { ticker: string; exchange: string }) {
  const capabilities = useTradingCapabilities();
  const { user } = useAuth();
  const { t } = useTranslation();
  if (!capabilities.data?.enabled) return null;
  return (
    <Card>
      <CardHeader title={t("trading.buy")} description={t("trading.simulated")} />
      <CardBody>
        {user ? <PurchaseForm key={`${user.id}:${ticker}:${exchange}`} ticker={ticker} exchange={exchange} />
          : <LocalizedLink to="/login" className="underline">{t("trading.signIn")}</LocalizedLink>}
      </CardBody>
    </Card>
  );
}

function PurchaseForm({ ticker, exchange }: { ticker: string; exchange: string }) {
  const { user } = useAuth();
  const { t } = useTranslation();
  const client = useQueryClient();
  const wallet = useTradingWallet(true);
  const [budget, setBudget] = useState("100");
  const [preview, setPreview] = useState<{ quote: TradingQuote; key: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const prepare = async () => {
    setBusy(true); setError(null); setSuccess(false);
    try {
      const quote = await api.tradingQuote({ side: "buy", ticker, exchange, budget });
      setPreview({ quote, key: crypto.randomUUID() });
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  };
  const buy = async () => {
    if (!preview) return;
    setBusy(true); setError(null);
    try {
      await api.buyTrade(preview.quote.id, preview.key);
      setPreview(null); setSuccess(true);
      await client.invalidateQueries({ queryKey: ["trading", user?.id] });
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <div className="flex max-w-xl flex-col gap-3">
      <p>{t("trading.balance")}: {wallet.data?.balance ?? "…"} {t("trading.credits")}</p>
      <p className="text-xs text-muted-foreground">{t("trading.creditHint")}</p>
      {wallet.error && <Alert tone="danger">{wallet.error.message}</Alert>}
      {preview ? <TradeConfirmation quote={preview.quote} busy={busy} onConfirm={buy} onCancel={() => setPreview(null)} /> : (
        <form onSubmit={(event) => { event.preventDefault(); void prepare(); }} className="flex flex-col gap-3">
          <Field label={t("trading.budget")}>
            {(id) => <Input id={id} type="number" min="0.00000001" max="1000000000000" step="0.00000001" required value={budget} onChange={(event) => setBudget(event.target.value)} />}
          </Field>
          <Button disabled={busy || !wallet.data}>{t("trading.previewBuy")}</Button>
        </form>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      {success && <Alert>{t("trading.bought")} <LocalizedLink to="/trades" className="underline">{t("trading.title")}</LocalizedLink></Alert>}
    </div>
  );
}
