import type { ButtonHTMLAttributes } from "react";
import { cx } from "./cx";

export type PillProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** Selected state — quick-pick roles, radius selector, detected-role chips. */
  selected?: boolean;
  /** Dashed outline for "add this one" suggestions. */
  dashed?: boolean;
};

export function Pill({
  selected = false,
  dashed = false,
  className,
  type = "button",
  ...rest
}: PillProps) {
  return (
    <button
      type={type}
      aria-pressed={selected}
      className={cx(
        // min-h-11 (44px) is the touch-target floor — px-3.5/py-1.5 alone
        // rendered at ~30px, too small to reliably tap on a phone.
        "inline-flex min-h-11 items-center gap-1.5 rounded-pill px-3.5 py-1.5",
        "text-[13px] font-medium transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong",
        "disabled:cursor-not-allowed disabled:opacity-50",
        dashed ? "border border-dashed" : "border",
        selected
          ? "bg-accent border-accent text-white"
          : "bg-surface-plain border-line-plain text-slate-muted hover:border-line hover:text-ink",
        className,
      )}
      {...rest}
    />
  );
}
