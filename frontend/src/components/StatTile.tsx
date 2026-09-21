import { cn } from "@/lib/utils";

/**
 * A single figure with its label. Direction is carried by an arrow as well as
 * colour, so the up/down reading never depends on colour alone.
 */
export function StatTile({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "neutral" | "up" | "down";
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          "tabular mt-1 text-xl font-semibold",
          tone === "up" && "text-[var(--success)]",
          tone === "down" && "text-[var(--destructive)]",
        )}
      >
        {tone === "up" ? "▲ " : tone === "down" ? "▼ " : ""}
        {value}
      </p>
      {hint ? <p className="mt-1 truncate text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
