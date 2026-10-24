import type { PaymentSelection } from "@/lib/trading";

/** Payment artwork is decorative; each control supplies its own readable label. */
// Official PayPal asset: https://www.paypalobjects.com/paypal-ui/logos/svg/paypal-mark-color.svg
export function PaymentBrand({ method }: { method: PaymentSelection["payment_method"] }) {
  if (method === "paypal") return <span className="payment-brand payment-brand-paypal" aria-hidden="true">
    <img src="/brands/paypal.svg" alt="" width="25" height="30" />
  </span>;
  if (method === "card") return <span className="payment-brand payment-brand-card" aria-hidden="true">
    <svg width="32" height="26" viewBox="0 0 32 26" fill="none">
      <rect x="1" y="3" width="30" height="21" rx="5" stroke="currentColor" strokeWidth="1.8" />
      <path d="M2 10h28M6 18h6M19 18h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  </span>;
  return <span className="payment-brand payment-brand-wallet" aria-hidden="true">TM<span className="payment-brand-dot" /></span>;
}
