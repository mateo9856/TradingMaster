import { useId } from "react";
import { useTranslation } from "react-i18next";

import { PaymentBrand } from "@/components/PaymentBrand";
import { formatCash } from "@/lib/format";
import type { PaymentAccounts, PaymentSelection } from "@/lib/trading";
import { cn } from "@/lib/utils";

export function PaymentFields({ value, onChange, accounts, walletBalance, funding = false, disabled = false }: {
  value: PaymentSelection; onChange: (value: PaymentSelection) => void;
  accounts?: PaymentAccounts; walletBalance?: string; funding?: boolean; disabled?: boolean;
}) {
  const { t } = useTranslation();
  const name = useId();
  const kind = value.payment_method === "card" ? value.card_type : value.payment_method;
  const account = kind === "credits" ? undefined : accounts?.accounts[kind];
  const methods = (funding ? ["card", "paypal"] : ["credits", "card", "paypal"]) as PaymentSelection["payment_method"][];
  const labels = { credits: t("payments.wallet"), card: t("trading.card"), paypal: t("trading.paypal") };
  const hints = { credits: walletBalance ? `${formatCash(walletBalance)} ${t("trading.credits")}` : t("payments.walletHint"),
    card: t("payments.cardHint"), paypal: t("payments.paypalHint") };
  return <div className="space-y-5">
    <fieldset className="min-w-0" disabled={disabled}>
      <legend className="mb-3 text-sm font-semibold">{t("payments.method")}</legend>
      <div className={cn("payment-methods", funding && "payment-methods-two")}>
        {methods.map((method) => <label key={method} className={cn("payment-option", value.payment_method === method && "is-selected", disabled && "is-disabled")}>
          <input className="sr-only" type="radio" name={name} value={method} aria-label={labels[method]}
            checked={value.payment_method === method} onChange={() => onChange(method === "card"
              ? { payment_method: "card", card_type: "debit" } : { payment_method: method })} />
          <span className="payment-option-check" aria-hidden="true">{value.payment_method === method ? "✓" : ""}</span>
          <PaymentBrand method={method} />
          <span className="mt-3 block text-sm font-semibold">{labels[method]}</span>
          <span className="mt-1 block text-xs text-muted-foreground">{hints[method]}</span>
        </label>)}
      </div>
    </fieldset>
    {value.payment_method === "card" && <fieldset className="min-w-0" disabled={disabled}>
      <legend className="mb-2 text-xs font-medium text-muted-foreground">{t("payments.cardType")}</legend>
      <div className="payment-segments">
        {(["debit", "credit"] as const).map((type) => <label key={type} className={cn("payment-segment", value.card_type === type && "is-selected")}>
          <input type="radio" className="sr-only" name={`${name}-card`} aria-label={t(`payments.${type}`)}
            checked={value.card_type === type} onChange={() => onChange({ payment_method: "card", card_type: type })} />
          {t(`payments.${type}`)}
        </label>)}
      </div>
    </fieldset>}
    {account && <div className="payment-account" aria-live="polite">
      <p>{t("payments.available")}: {formatCash(account.available)} USD</p>
      {account.debt !== null && <p>{t("payments.debt")}: {formatCash(account.debt)} USD</p>}
      <p className="text-xs text-muted-foreground">{t("payments.transactionLimit")}: {formatCash(account.transaction_limit)} USD</p>
    </div>}
  </div>;
}
