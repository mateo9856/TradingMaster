import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type Tone = "neutral" | "success" | "warning" | "danger" | "info";

const TONES: Record<Tone, string> = {
  neutral: "border-border bg-muted text-muted-foreground",
  success: "border-transparent bg-[color-mix(in_oklab,var(--success)_20%,transparent)] text-[var(--success)]",
  warning: "border-transparent bg-[color-mix(in_oklab,var(--warning)_20%,transparent)] text-[var(--warning)]",
  danger: "border-transparent bg-[color-mix(in_oklab,var(--destructive)_20%,transparent)] text-[var(--destructive)]",
  info: "border-transparent bg-[color-mix(in_oklab,var(--primary)_20%,transparent)] text-[var(--primary)]",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function Badge({ className, tone = "neutral", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
      {...props}
    />
  );
}
