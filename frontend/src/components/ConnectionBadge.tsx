import { Badge } from "@/components/ui/badge";
import type { ConnectionStatus } from "@/hooks/useLiveCandles";

const LABELS: Record<ConnectionStatus, { text: string; tone: "success" | "warning" | "danger" | "neutral" }> = {
  live: { text: "Live", tone: "success" },
  connecting: { text: "Connecting…", tone: "warning" },
  closed: { text: "Reconnecting…", tone: "warning" },
  error: { text: "Stream error", tone: "danger" },
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
  const { text, tone } = LABELS[status];
  return (
    <Badge tone={tone} title={error ?? undefined} aria-live="polite">
      <span
        aria-hidden
        className="size-1.5 rounded-full bg-current"
        style={{ animation: status === "live" ? "pulse 2s ease-in-out infinite" : undefined }}
      />
      {text}
      {typeof count === "number" && count > 0 ? (
        <span className="tabular opacity-70">· {count} msg</span>
      ) : null}
    </Badge>
  );
}
