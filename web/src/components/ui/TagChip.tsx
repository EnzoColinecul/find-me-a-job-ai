import type { HTMLAttributes } from "react";
import { cx } from "./cx";

/**
 * Tones follow the mockups' semantic colouring: what the agent is doing right
 * now (`working`), what it found (`found`), what it skipped (`muted`), and the
 * source label on a result link (`info`).
 */
export type TagTone = "info" | "found" | "working" | "muted" | "alert";

const TONES: Record<TagTone, string> = {
  info: "bg-accent/10 text-accent",
  found: "bg-success/12 text-success-deep",
  working: "bg-warn/15 text-warn",
  muted: "bg-paper-deep text-slate-muted",
  alert: "bg-pin/12 text-pin",
};

export type TagChipProps = HTMLAttributes<HTMLSpanElement> & {
  tone?: TagTone;
};

export function TagChip({ tone = "muted", className, ...rest }: TagChipProps) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-tag px-1.5 py-0.5",
        "text-[10px] font-bold uppercase tracking-[0.06em]",
        TONES[tone],
        className,
      )}
      {...rest}
    />
  );
}
