import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { formatCash, formatExchange } from "@/lib/format";
import type { TradingQuote } from "@/lib/trading";

export function TradeConfirmation({ quote, busy, onConfirm, onCancel, onRefresh }: {
  quote: TradingQuote; busy: boolean; onConfirm: () => void; onCancel: () => void; onRefresh?: () => void;
}) {
  const { t } = useTranslation();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, []);
  const expired = now >= Date.parse(quote.expires_at);
  const seconds = Math.max(0, Math.ceil((Date.parse(quote.expires_at) - now) / 1000));
  return (
    <div className="payment-quote flex flex-col gap-4" aria-label={t("trading.preview")}>
      <p className="font-medium">{quote.ticker} · {formatExchange(quote.exchange)}</p>
      <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-4 text-sm tabular-nums">
        <dt>{t("trading.quantity")}</dt><dd>{quote.quantity}</dd>
        <dt>{t("trading.bid")}</dt><dd>{quote.bid} USD</dd>
        <dt>{t("trading.ask")}</dt><dd>{quote.ask} USD</dd>
        <dt>{t("trading.spread")}</dt><dd>{quote.spread} USD ({quote.spread_percent}%)</dd>
        <dt>{t(quote.side === "buy" ? "trading.cost" : "trading.sellValue")}</dt><dd className="font-semibold">{formatCash(quote.amount)} {t("trading.credits")}</dd>
      </dl>
      <p className={expired ? "text-sm text-destructive" : "text-sm font-medium text-primary"}>{t("payments.quoteCountdown", { seconds })}</p>
      <p className="text-xs text-muted-foreground">{t("trading.quoteTime")} {quote.source_at ?? quote.received_at}</p>
      <p className="text-xs text-muted-foreground">{t("payments.expiresAt")}: {new Date(quote.expires_at).toLocaleTimeString()}</p>
      {quote.delayed && <p className="text-sm text-amber-600">{t("trading.delayed")}</p>}
      <p className="text-xs text-muted-foreground">{expired ? t("trading.expired") : t("trading.confirmHint")}</p>
      <div className="flex flex-wrap gap-2">
        <Button className="payment-primary grow" disabled={busy || expired} onClick={onConfirm}>{t(quote.side === "buy" ? "trading.confirmBuy" : "trading.confirmSell")}</Button>
        <Button variant="secondary" disabled={busy} onClick={onCancel}>{t("trading.cancel")}</Button>
        {expired && onRefresh && <Button variant="secondary" disabled={busy} onClick={onRefresh}>{t("payments.refreshQuote")}</Button>}
      </div>
    </div>
  );
}
