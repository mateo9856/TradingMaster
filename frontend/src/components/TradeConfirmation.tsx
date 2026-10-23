import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { formatExchange } from "@/lib/format";
import type { TradingQuote } from "@/lib/trading";

export function TradeConfirmation({ quote, busy, onConfirm, onCancel }: {
  quote: TradingQuote; busy: boolean; onConfirm: () => void; onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, []);
  const expired = now >= Date.parse(quote.expires_at);
  return (
    <div className="flex flex-col gap-3 rounded-md border border-border p-4" aria-label={t("trading.preview")}>
      <p className="font-medium">{quote.ticker} · {formatExchange(quote.exchange)}</p>
      <dl className="grid grid-cols-2 gap-2 text-sm tabular-nums">
        <dt>{t("trading.quantity")}</dt><dd>{quote.quantity}</dd>
        <dt>{t("trading.bid")}</dt><dd>{quote.bid} USD</dd>
        <dt>{t("trading.ask")}</dt><dd>{quote.ask} USD</dd>
        <dt>{t("trading.spread")}</dt><dd>{quote.spread} USD ({quote.spread_percent}%)</dd>
        <dt>{t(quote.side === "buy" ? "trading.cost" : "trading.sellValue")}</dt><dd>{quote.amount} {t("trading.credits")}</dd>
      </dl>
      <p className="text-xs text-muted-foreground">{t("trading.quoteTime")} {quote.source_at ?? quote.received_at}</p>
      {quote.delayed && <p className="text-sm text-amber-600">{t("trading.delayed")}</p>}
      <p className="text-xs text-muted-foreground">{expired ? t("trading.expired") : t("trading.confirmHint")}</p>
      <div className="flex gap-2">
        <Button disabled={busy || expired} onClick={onConfirm}>{t(quote.side === "buy" ? "trading.confirmBuy" : "trading.confirmSell")}</Button>
        <Button variant="secondary" disabled={busy} onClick={onCancel}>{t("trading.cancel")}</Button>
      </div>
    </div>
  );
}
