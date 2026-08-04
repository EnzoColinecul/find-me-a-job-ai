import type { HTMLAttributes } from "react";
import { cx } from "./cx";

export type CardProps = HTMLAttributes<HTMLDivElement> & {
  /**
   * `paper` — cream surface on the paper background (result cards, panels).
   * `plain` — pure white sheet that floats over the map (login, dialogs).
   */
  tone?: "paper" | "plain";
  /** Panel radius + heavy shadow, for sheets sitting over the map. */
  elevated?: boolean;
};

export function Card({
  tone = "paper",
  elevated = false,
  className,
  ...rest
}: CardProps) {
  return (
    <div
      className={cx(
        tone === "paper"
          ? "bg-surface border border-line"
          : "bg-surface-plain border border-line-plain",
        elevated ? "rounded-sheet shadow-sheet" : "rounded-card shadow-card",
        className,
      )}
      {...rest}
    />
  );
}
