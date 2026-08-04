import type { Me } from "@/lib/api";
import { cx } from "./ui/cx";

export function initials(me: Me): string {
  const source = me.name || me.email;
  return (
    source
      .split(/[\s@.]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0]?.toUpperCase() ?? "")
      .join("") || "?"
  );
}

/**
 * `quiet` is the neutral disc in the home screen's top-right corner; `accent`
 * is the filled blue one in the workspace rail's profile row.
 */
export default function Avatar({
  me,
  tone = "quiet",
  size = 32,
  className,
}: {
  me: Me;
  tone?: "quiet" | "accent";
  size?: number;
  className?: string;
}) {
  return (
    <span
      title={me.name || me.email}
      className={cx(
        "flex flex-none items-center justify-center rounded-full text-[12px] font-bold",
        tone === "accent"
          ? "bg-accent-strong text-white"
          : "border border-line-plain bg-paper-deep text-slate-muted",
        className,
      )}
      style={{ width: size, height: size }}
    >
      {initials(me)}
    </span>
  );
}
