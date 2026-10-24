import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { LocalizedLink } from "@/components/LocalizedLink";
import { PaymentBrand } from "@/components/PaymentBrand";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { formatCash } from "@/lib/format";
import type { PaymentSelection } from "@/lib/trading";
import { cn } from "@/lib/utils";

export function PaymentLayout({ title, funding = false, children }: { title: string; funding?: boolean; children: ReactNode }) {
  const { t } = useTranslation();
  return <section className="payment-shell">
    <LocalizedLink to={funding ? "/trades" : "/markets"} className="payment-back">← {t(funding ? "trading.title" : "common.allMarkets")}</LocalizedLink>
    <div className="payment-heading">
      <div>
        <span className="payment-eyebrow"><span />{t("payments.simulation")}</span>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">{title}<span className="text-primary" aria-hidden="true">.</span></h1>
        <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">{t(funding ? "payments.fundingIntro" : "payments.checkoutIntro")}</p>
      </div>
      <div className="payment-heading-mark" aria-hidden="true">TM<span>↗</span></div>
    </div>
    {children}
    <p className="payment-disclaimer">{t("payments.simulatorHint")}</p>
  </section>;
}

export function PaymentSteps({ step }: { step: 0 | 1 | 2 }) {
  const { t } = useTranslation();
  return <ol className="payment-steps" aria-label={t("payments.progress")}>
    {["paymentStep", "reviewStep", "completeStep"].map((label, index) => <li key={label}
      className={cn(index === step && "is-current", index < step && "is-done")} aria-current={index === step ? "step" : undefined}>
      <span className="payment-step-number" aria-hidden="true">{index < step ? "✓" : `0${index + 1}`}</span>
      <span>{t(`payments.${label}`)}</span>
    </li>)}
  </ol>;
}

export function PaymentBudget({ value, onChange, disabled, funding = false }: {
  value: string; onChange: (value: string) => void; disabled: boolean; funding?: boolean;
}) {
  const { t } = useTranslation();
  return <div className="mb-7">
    <Field label={t(funding ? "payments.fundingAmount" : "payments.budget")}>
      {(id) => <div className="payment-amount-input">
        <span aria-hidden="true">$</span>
        <Input id={id} type="number" min="0.00000001" max="1000000000000" step="0.00000001" required
          disabled={disabled} value={value} placeholder="100.00" onChange={(event) => onChange(event.target.value)} />
        <span className="payment-amount-currency" aria-hidden="true">USD</span>
      </div>}
    </Field>
    <div className="mt-3 flex flex-wrap gap-2">
      {["100", "250", "500"].map((amount) => <button type="button" key={amount} className="payment-preset"
        disabled={disabled} onClick={() => onChange(amount)}>${formatCash(amount)}</button>)}
    </div>
  </div>;
}

export function PaymentSummary({ amount, amountLabel, payment, balance, title, ticker, exchange, quantity, funding = false }: {
  amount: string; amountLabel: string; payment: PaymentSelection; balance?: string;
  title: string; ticker?: string; exchange?: string; quantity?: string; funding?: boolean;
}) {
  const { t } = useTranslation();
  const method = payment.payment_method === "card" ? t(`payments.${payment.card_type}`)
    : t(payment.payment_method === "credits" ? "payments.wallet" : "trading.paypal");
  return <aside className="payment-summary" aria-label={t(funding ? "payments.fundingSummary" : "payments.orderSummary")}>
    <div className="payment-summary-hero">
      <p className="text-xs font-medium uppercase tracking-[0.16em] opacity-80">{t(funding ? "payments.fundingSummary" : "payments.orderSummary")}</p>
      <div className="mt-7 flex items-center gap-3">
        <span className="payment-asset-mark" aria-hidden="true">{funding ? "↗" : ticker?.split("/")[0].slice(0, 3)}</span>
        <div className="min-w-0"><h2 className="truncate text-lg font-semibold">{title}</h2>
          <p className="mt-1 text-xs opacity-75">{funding ? t("payments.wallet") : `${ticker} · ${exchange}`}</p>
        </div>
      </div>
      <div className="mt-9 border-t border-white/20 pt-5">
        <p className="text-xs opacity-80">{amountLabel}</p>
        <p className="payment-summary-amount"><span>{formatCash(amount)}</span><span>USD</span></p>
      </div>
    </div>
    <div className="payment-summary-body">
      {quantity && <div className="payment-summary-row"><span>{t("trading.quantity")}</span><strong>{quantity}</strong></div>}
      {!funding && !quantity && <p className="text-xs leading-relaxed text-muted-foreground">{t("payments.quantityHint")}</p>}
      <div className="payment-summary-row mt-5"><span>{t("payments.method")}</span>
        <span className="flex items-center gap-2 font-medium"><PaymentBrand method={payment.payment_method} />{method}</span>
      </div>
      <div className="payment-summary-balance">
        <p>{t("payments.simulatedBalance")}: {balance === undefined ? "…" : formatCash(balance)} {t("trading.credits")}</p>
        {!funding && <LocalizedLink to="/wallet" className="mt-2 inline-block font-medium text-primary hover:underline">{t("payments.addFunds")} <span aria-hidden="true">↗</span></LocalizedLink>}
      </div>
      <p className="mt-4 text-xs leading-relaxed text-muted-foreground">{t("trading.creditHint")}</p>
    </div>
  </aside>;
}

export function PaymentCompletion({ funding = false, marketPath = "/markets", onAgain }: { funding?: boolean; marketPath?: string; onAgain: () => void }) {
  const { t } = useTranslation();
  return <div className="payment-completion" role="status">
    <span className="payment-completion-mark" aria-hidden="true">✓</span>
    <span className="payment-eyebrow mt-6">{t("payments.completeStep")}</span>
    <h2 className="mt-3 text-2xl font-semibold tracking-tight">{t(funding ? "payments.funded" : "trading.bought")}</h2>
    <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted-foreground">{t("payments.completedHint")}</p>
    <div className="mt-7 flex w-full flex-col gap-3">
      <LocalizedLink to={funding ? "/markets" : "/trades"} className="payment-primary-link">{t(funding ? "common.allMarkets" : "trading.title")} <span aria-hidden="true">↗</span></LocalizedLink>
      {!funding && <LocalizedLink to={marketPath} className="text-sm text-muted-foreground hover:text-foreground">{t("payments.backToMarket")}</LocalizedLink>}
      <Button variant="ghost" onClick={onAgain}>{t("payments.startAgain")}</Button>
    </div>
  </div>;
}
