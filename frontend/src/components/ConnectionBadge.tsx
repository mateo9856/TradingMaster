import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import type { ConnectionStatus } from "@/hooks/useLiveCandles";

const TONES: Record<ConnectionStatus, "success" | "warning" | "danger" | "neutral"> = {
  live: "success",
  connecting: "warning",
  closed: "warning",
  error: "danger",
};

export function ConnectionBadge({
  status,
  error,
  count,
}: {
  status: ConnectionStatus;
  error?: string | null;
  count?: number;
}) {
  const { t } = useTranslation();
  const tone = TONES[status];
  const text = t(`connection.${status}`);
  return (
    <Badge tone={tone} title={error ?? undefined} aria-live="polite">
      <span
        aria-hidden
        className="size-1.5 rounded-full bg-current"
        style={{ animation: status === "live" ? "pulse 2s ease-in-out infinite" : undefined }}
      />
      {text}
      {typeof count === "number" && count > 0 ? (
        <span className="tabular opacity-70">· {t("connection.messages", { count })}</span>
      ) : null}
    </Badge>
  );
}
