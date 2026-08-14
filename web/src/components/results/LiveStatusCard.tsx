"use client";

import type { Search } from "@/lib/api";
import { currentAction } from "@/lib/trace-narrate";

/**
 * The card over the bottom-left of the map while a search runs: what I'm doing
 * right now, how far through I am, and a bar.
 *
 * It mirrors the newest trace row rather than saying anything of its own, so
 * the two can't disagree.
 */
export default function LiveStatusCard({ search }: { search: Search }) {
  const { done, total } = search.progress ?? { done: 0, total: 0 };
  const action = currentAction(search);
  // +1 because the one being worked on isn't finished yet — but never overstate
  // past the total.
  const looking = total ? Math.min(done + 1, total) : 0;
  const pct = total ? Math.round((done / total) * 100) : 0;

  return (
    <div className="absolute right-5 bottom-5 left-5 flex items-center gap-3 rounded-float bg-surface-plain px-4 py-3 shadow-float lg:right-auto lg:max-w-[560px]">
      <span
        aria-hidden="true"
        className="block h-4 w-4 flex-none animate-[spin_0.9s_linear_infinite] rounded-full border-2 border-accent-strong/25 border-t-accent-strong"
      />

      <div className="min-w-0 flex-1">
        <p className="m-0 truncate text-[13px] font-semibold text-ink">
          {action ?? "Getting started…"}
        </p>
        <p className="m-0 text-[11.5px] text-slate-muted" aria-live="polite">
          {total
            ? `Looking at ${looking} of ${total} place${total === 1 ? "" : "s"} nearby`
            : "Finding places nearby"}
        </p>
      </div>

      {total > 0 && (
        <div
          role="progressbar"
          aria-valuenow={done}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-label="Companies investigated"
          className="hidden h-1 w-[140px] flex-none overflow-hidden rounded-pill bg-paper-deep sm:block"
        >
          <div
            className="h-full rounded-pill bg-accent-strong transition-[width] duration-700 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  );
}

/**
 * Expanding rings over the map centre while work is happening.
 *
 * Deliberately anchored to the search centre, not to individual companies: we
 * don't persist per-company coordinates, and a ring that appeared to point at a
 * specific venue would be claiming something we can't back up.
 */
export function MapActivityPing() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute top-1/2 left-1/2 h-24 w-24 -translate-x-1/2 -translate-y-1/2"
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="absolute inset-0 rounded-full border-2 border-accent-strong animate-[mapPing_2.4s_ease-out_infinite]"
          style={{ animationDelay: `${i * 0.8}s` }}
        />
      ))}
    </div>
  );
}
