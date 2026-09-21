import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type Tone = "info" | "warning" | "danger" | "success";

const TONES: Record<Tone, string> = {
  info: "border-border bg-muted text-foreground",
  success: "border-[var(--success)]/40 bg-[color-mix(in_oklab,var(--success)_12%,transparent)]",
  warning: "border-[var(--warning)]/40 bg-[color-mix(in_oklab,var(--warning)_12%,transparent)]",
  danger: "border-destructive/40 bg-[color-mix(in_oklab,var(--destructive)_12%,transparent)]",
};

export function Alert({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: Tone;
  title?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div role="status" className={cn("rounded-md border p-3 text-sm", TONES[tone], className)}>
      {title ? <p className="font-medium">{title}</p> : null}
      {children ? <div className={cn("text-sm", title && "mt-1 text-muted-foreground")}>{children}</div> : null}
    </div>
  );
}
