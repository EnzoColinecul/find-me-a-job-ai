"use client";

import { useEffect, useRef } from "react";
import type { Search, TraceStep } from "@/lib/api";
import { cx } from "../ui/cx";

/** Tag colours from the mockup: found → success, checking → warn, skipping → muted. */
const TAG_STYLE: Record<TraceStep["tag"], string> = {
  searching: "bg-accent/12 text-accent",
  checking: "bg-warn/15 text-warn-deep",
  found: "bg-success/15 text-success-deep",
  skipping: "bg-paper-deep text-slate-muted",
};

const TAG_LABEL: Record<TraceStep["tag"], string> = {
  searching: "Searching",
  checking: "Checking",
  found: "Found",
  skipping: "Skipping",
};

function Row({ step }: { step: TraceStep }) {
  return (
    <li className="flex items-baseline gap-2 border-b border-line-cool/60 py-2 last:border-b-0">
      <span
        className={cx(
          "flex-none rounded-pill px-1.5 py-px text-[10px] font-bold",
          TAG_STYLE[step.tag],
        )}
      >
        {TAG_LABEL[step.tag]}
      </span>
      <span className="min-w-0 flex-1 truncate text-[12px] text-ink">
        {step.text}
      </span>
      <code className="flex-none font-mono text-[10.5px] text-slate-faint">
        {step.tool}
      </code>
      {step.meta && (
        <span className="max-w-[38%] flex-none truncate text-[10.5px] text-slate-muted">
          {step.meta}
        </span>
      )}
    </li>
  );
}

/**
 * Mockup 5 — "What I'm doing. Nothing hidden."
 *
 * Every row is a call the agent actually made; the backend never synthesises
 * steps to make the panel look busier. If the list is empty while a search runs
 * that is real information (discovery hasn't reported yet), so it says so rather
 * than showing a fake placeholder.
 */
export default function TracePanel({
  search,
  onStop,
  stopping,
  stopError,
}: {
  search: Search;
  onStop: () => void;
  stopping: boolean;
  stopError: string | null;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // Same defence as the page: never assume the API sent these.
  const steps = search.steps ?? [];
  const stepCount = steps.length;
  const live = search.status === "pending" || search.status === "running";

  // Follow the newest row while the search is live. Only when the user is
  // already near the bottom — yanking the list out from under someone reading
  // an earlier step would be worse than not following at all.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !live) return;
    const nearBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [stepCount, live]);

  const { done, total } = search.progress ?? { done: 0, total: 0 };

  return (
    <div className="flex h-full flex-col">
      <div className="flex-none border-b border-rail-line px-5 pt-[18px] pb-3.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="m-0 text-[15px] font-bold text-ink">
              What I&apos;m doing
            </h2>
            <p className="mt-[3px] mb-0 text-[11.5px] text-slate-muted">
              Nothing hidden — every step is a real call.
            </p>
          </div>
          {live && (
            <button
              type="button"
              onClick={onStop}
              disabled={stopping}
              className="flex-none rounded-pill border border-line-plain px-3 py-1 text-[11.5px] font-semibold text-ink transition-colors duration-150 hover:border-pin hover:text-pin focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-pin disabled:opacity-50"
            >
              {stopping ? "Stopping…" : "Stop"}
            </button>
          )}
        </div>

        {total > 0 && (
          <div className="mt-3">
            <p
              className="m-0 mb-1.5 text-[11.5px] font-semibold text-ink"
              aria-live="polite"
            >
              Looking at {Math.min(done + (live ? 1 : 0), total)} of {total}{" "}
              place{total === 1 ? "" : "s"} nearby
            </p>
            <div
              role="progressbar"
              aria-valuenow={done}
              aria-valuemin={0}
              aria-valuemax={total}
              aria-label="Companies investigated"
              className="h-1 overflow-hidden rounded-pill bg-paper-deep"
            >
              <div
                className="h-full rounded-pill bg-accent-strong transition-[width] duration-500"
                style={{ width: `${Math.round((done / total) * 100)}%` }}
              />
            </div>
          </div>
        )}

        {stopError && (
          <p role="alert" className="mt-2 mb-0 text-[11.5px] text-pin">
            {stopError}
          </p>
        )}
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-5">
        {stepCount === 0 ? (
          <p className="mt-4 text-[12px] leading-normal text-slate-muted">
            {live
              ? "Starting up — the first step appears as soon as I've found places nearby."
              : "No steps were recorded for this search."}
          </p>
        ) : (
          <ul className="m-0 list-none p-0">
            {steps.map((s, i) => (
              <Row key={`${s.at}-${i}`} step={s} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
