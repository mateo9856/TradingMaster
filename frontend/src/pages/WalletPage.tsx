import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { LocalizedLink } from "@/components/LocalizedLink";
import { PaymentBrand } from "@/components/PaymentBrand";
import { PaymentFields } from "@/components/PaymentFields";
import { PaymentBudget, PaymentCompletion, PaymentLayout, PaymentSteps, PaymentSummary } from "@/components/PaymentLayout";
import { Seo } from "@/components/Seo";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatCash } from "@/lib/format";
import { paymentError, usePaymentAccounts, useTradingCapabilities, useTradingWallet } from "@/lib/trading";
import type { PaymentSelection } from "@/lib/trading";

export function WalletPage() {
  const { user, loading } = useAuth();
  const capabilities = useTradingCapabilities();
  const { t } = useTranslation();
  return <PaymentLayout title={t("payments.addFunds")} funding>
    <Seo title={t("seo.wallet_title")} noindex />
    {loading || capabilities.isPending ? <p>{t("common.loading")}</p>
      : capabilities.error ? <Alert tone="danger">{paymentError(capabilities.error, t)}</Alert>
      : !user ? <LocalizedLink to="/login">{t("trading.signIn")}</LocalizedLink>
      : !capabilities.data?.enabled ? <Alert>{t("trading.disabled")}</Alert>
      : <FundingForm key={user.id} />}
  </PaymentLayout>;
}

type Deposit = { amount: string; payment: PaymentSelection };

function FundingForm() {
  const { user } = useAuth();
  const { t } = useTranslation();
  const client = useQueryClient();
  const wallet = useTradingWallet(true);
  const accounts = usePaymentAccounts(Boolean(wallet.data));
  const [amount, setAmount] = useState("100");
  const [payment, setPayment] = useState<PaymentSelection>({ payment_method: "card", card_type: "debit" });
  const [review, setReview] = useState<Deposit | null>(null);
  const [completed, setCompleted] = useState<Deposit | null>(null);
  const requestKey = useRef<string | null>(null);
  const submitting = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changed = () => { requestKey.current = null; setError(null); };
  const fund = async () => {
    if (!review || submitting.current) return;
    submitting.current = true; setBusy(true); setError(null);
    requestKey.current ??= crypto.randomUUID();
    try {
      await api.fundWallet(review.amount, requestKey.current, review.payment);
      requestKey.current = null; setCompleted(review); setReview(null);
      await client.invalidateQueries({ queryKey: ["trading", user?.id] });
    } catch (caught) {
      setError(paymentError(caught, t));
      await client.invalidateQueries({ queryKey: ["trading", user?.id] });
    } finally { submitting.current = false; setBusy(false); }
  };
  const shown = completed ?? review ?? { amount, payment };
  const method = shown.payment.payment_method === "card" ? t(`payments.${shown.payment.card_type}`) : t("trading.paypal");
  return <>
    <PaymentSteps step={completed ? 2 : review ? 1 : 0} />
    <div className="payment-columns">
      <div className="payment-panel">
        {completed ? <PaymentCompletion funding onAgain={() => { setCompleted(null); changed(); }} /> : <>
          <div className="payment-panel-heading">
            <span className="payment-section-number" aria-hidden="true">{review ? "02" : "01"}</span>
            <div><h2 className="text-lg font-semibold">{t(review ? "payments.reviewTitle" : "payments.paymentStep")}</h2>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{t(review ? "payments.fundingReviewHint" : "payments.paymentHint")}</p></div>
          </div>
          {review ? <div>
            <div className="payment-deposit-review">
              <PaymentBrand method={review.payment.payment_method} />
              <p className="mt-4 text-sm text-muted-foreground">{method} <span aria-hidden="true">→</span> {t("payments.wallet")}</p>
              <p className="mt-3 text-4xl font-semibold tabular-nums">{formatCash(review.amount)} <span className="text-sm text-muted-foreground">USD</span></p>
              <p className="mt-4 text-xs text-muted-foreground">{t("trading.creditHint")}</p>
            </div>
            <Button className="payment-primary mt-6 w-full" disabled={busy} onClick={() => void fund()}>{t("payments.confirmFunding")}</Button>
            <Button variant="ghost" className="mt-2 w-full" disabled={busy} onClick={() => { setReview(null); changed(); }}>{t("trading.cancel")}</Button>
          </div> : <form onSubmit={(event) => { event.preventDefault(); setReview({ amount, payment }); setError(null); }}>
            <PaymentBudget value={amount} onChange={(value) => { setAmount(value); changed(); }} disabled={busy} funding />
            <PaymentFields value={payment} onChange={(value) => { setPayment(value); changed(); }} accounts={accounts.data} funding disabled={busy} />
            <Button className="payment-primary mt-7 w-full" disabled={busy || !wallet.data || !accounts.data}>{t("payments.reviewDeposit")} <span aria-hidden="true">↗</span></Button>
          </form>}
        </>}
        {wallet.error && <Alert className="mt-4" tone="danger">{paymentError(wallet.error, t)}</Alert>}
        {accounts.error && <Alert className="mt-4" tone="danger">{paymentError(accounts.error, t)}</Alert>}
        {error && <Alert className="mt-4" tone="danger">{error}</Alert>}
      </div>
      <PaymentSummary title={t("payments.addFunds")} amount={shown.amount} payment={shown.payment} balance={wallet.data?.balance}
        amountLabel={t(completed ? "payments.paid" : "payments.depositTotal")} funding />
    </div>
  </>;
}
