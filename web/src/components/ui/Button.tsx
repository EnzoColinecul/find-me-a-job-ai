import type { ButtonHTMLAttributes } from "react";
import { cx } from "./cx";

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent text-white border border-accent hover:bg-accent-strong hover:border-accent-strong",
  secondary:
    "bg-surface-plain text-ink border border-line-plain shadow-card hover:border-line",
  ghost:
    "bg-transparent text-accent-strong border border-transparent hover:bg-paper-deep",
};

const SIZES: Record<Size, string> = {
  sm: "text-[13px] px-3 py-1.5",
  md: "text-sm px-[18px] py-3",
  lg: "text-[15px] px-6 py-3.5",
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  /** Stretch to the width of the parent — the mockups' full-width CTAs. */
  block?: boolean;
};

export function Button({
  variant = "primary",
  size = "md",
  block = false,
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(
        "inline-flex items-center justify-center gap-2.5 rounded-panel font-semibold",
        "transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        block && "w-full",
        className,
      )}
      {...rest}
    />
  );
}
