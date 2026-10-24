import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { LocalizedLink } from "@/components/LocalizedLink";
import { PaymentFields } from "@/components/PaymentFields";
import { PaymentBudget, PaymentCompletion, PaymentLayout, PaymentSteps, PaymentSummary } from "@/components/PaymentLayout";
import { Seo } from "@/components/Seo";
import { TradeConfirmation } from "@/components/TradeConfirmation";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useLanguage } from "@/hooks/useLanguage";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatExchange } from "@/lib/format";
import { marketName, marketSlug } from "@/lib/market";
import { paymentError, usePaymentAccounts, useTradingCapabilities, useTradingWallet } from "@/lib/trading";
import type { PaymentSelection, TradingQuote } from "@/lib/trading";

export function CheckoutPage() {
  const { user, loading } = useAuth();
  const { t } = useTranslation();
  const capabilities = useTradingCapabilities();
  const [params] = useSearchParams();
  const ticker = params.get("ticker");
  const exchange = params.get("exchange");
  return <PaymentLayout title={t("payments.checkout")}>
    <Seo title={t("seo.checkout_title")} noindex />
    {loading || capabilities.isPending ? <p>{t("common.loading")}</p>
      : capabilities.error ? <Alert tone="danger">{paymentError(capabilities.error, t)}</Alert>
      : !user ? <LocalizedLink to="/login">{t("trading.signIn")}</LocalizedLink>
      : !capabilities.data?.enabled ? <Alert>{t("trading.disabled")}</Alert>
      : !ticker || !exchange ? <LocalizedLink to="/markets">{t("payments.chooseAsset")}</LocalizedLink>
      : <CheckoutForm key={`${user.id}:${ticker}:${exchange}`} ticker={ticker} exchange={exchange} initialBudget={params.get("budget") ?? "100"} />}
  </PaymentLayout>;
}

type PurchasePreview = { quote: TradingQuote; key: string; payment: PaymentSelection };

export function CheckoutForm({ ticker, exchange, initialBudget = "100" }: {
  ticker: string; exchange: string; initialBudget?: string;
}) {
  const { user } = useAuth();
  const { t } = useTranslation();
  const language = useLanguage();
  const client = useQueryClient();
  const wallet = useTradingWallet(true);
  const accounts = usePaymentAccounts(Boolean(wallet.data));
  const markets = useQuery({ queryKey: ["markets", language], queryFn: () => api.markets(language), staleTime: 60_000, retry: false });
  const market = markets.data?.find((item) => item.ticker === ticker);
  const [budget, setBudget] = useState(initialBudget);
  const [payment, setPayment] = useState<PaymentSelection>({ payment_method: "credits" });
  const [preview, setPreview] = useState<PurchasePreview | null>(null);
  const [completed, setCompleted] = useState<PurchasePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const prepare = async () => {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setPreview(null); setError(null);
    try {
      const quote = await api.tradingQuote({ side: "buy", ticker, exchange, budget });
      setPreview({ quote, key: crypto.randomUUID(), payment });
    } catch (caught) { setError(paymentError(caught, t)); }
    finally { submitting.current = false; setBusy(false); }
  };
  const buy = async () => {
    if (!preview || submitting.current) return;
    submitting.current = true; setBusy(true); setError(null);
    try {
      await api.buyTrade(preview.quote.id, preview.key, preview.payment);
      setCompleted(preview); setPreview(null);
      await client.invalidateQueries({ queryKey: ["trading", user?.id] });
    } catch (caught) {
      setError(paymentError(caught, t));
      await client.invalidateQueries({ queryKey: ["trading", user?.id] });
    } finally { submitting.current = false; setBusy(false); }
  };
  const shown = completed ?? preview;
  return <>
    <PaymentSteps step={completed ? 2 : preview ? 1 : 0} />
    <div className="payment-columns">
      <div className="payment-panel">
        {completed ? <PaymentCompletion marketPath={market ? `/markets/${marketSlug(market)}` : "/markets"}
          onAgain={() => { setCompleted(null); setError(null); }} /> : <>
          <div className="payment-panel-heading">
            <span className="payment-section-number" aria-hidden="true">{preview ? "02" : "01"}</span>
            <div><h2 className="text-lg font-semibold">{t(preview ? "payments.reviewTitle" : "payments.paymentStep")}</h2>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{t(preview ? "payments.reviewHint" : "payments.paymentHint")}</p></div>
          </div>
          {preview ? <TradeConfirmation key={preview.key} quote={preview.quote} busy={busy} onConfirm={() => void buy()}
            onCancel={() => { setPreview(null); setError(null); }} onRefresh={() => void prepare()} />
            : <form onSubmit={(event) => { event.preventDefault(); void prepare(); }}>
              <PaymentBudget value={budget} onChange={(value) => { setBudget(value); setError(null); }} disabled={busy} />
              <PaymentFields value={payment} onChange={(value) => { setPayment(value); setError(null); }}
                accounts={accounts.data} walletBalance={wallet.data?.balance} disabled={busy} />
              <Button className="payment-primary mt-7 w-full" disabled={busy || !wallet.data || (payment.payment_method !== "credits" && !accounts.data)}>
                {busy ? t("common.loading") : t("trading.previewBuy")} <span aria-hidden="true">↗</span>
              </Button>
              <p className="mt-3 text-center text-xs text-muted-foreground">{t("payments.previewHint")}</p>
            </form>}
        </>}
        {wallet.error && <Alert className="mt-4" tone="danger">{paymentError(wallet.error, t)}</Alert>}
        {accounts.error && <Alert className="mt-4" tone="danger">{paymentError(accounts.error, t)}</Alert>}
        {error && <Alert className="mt-4" tone="danger">{error}</Alert>}
      </div>
      <PaymentSummary title={market ? marketName(market) : ticker} ticker={ticker} exchange={formatExchange(exchange)}
        amount={shown?.quote.amount ?? budget} amountLabel={t(completed ? "payments.paid" : preview ? "payments.total" : "payments.budgetTotal")}
        payment={shown?.payment ?? payment} balance={wallet.data?.balance} quantity={shown?.quote.quantity} />
    </div>
  </>;
}
