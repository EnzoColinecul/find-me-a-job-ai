"use client";

import { useState } from "react";
import type { Search, TraceStep } from "@/lib/api";
import { currentAction, narrate, toolLabel } from "@/lib/trace-narrate";
import { cx } from "../ui/cx";

/** Tag colours: found → success, checking → warn, skipping → muted. */
const TAG_STYLE: Record<TraceStep["tag"], string> = {
  searching: "text-accent",
  checking: "text-accent",
  found: "text-success-deep",
  // Was `slate-faint` (~2.6:1) at 10.5px — below AA, and this is the tag that
  // explains why something was dropped, so it's the last one to whisper.
  skipping: "text-slate-muted",
};

const TAG_LABEL: Record<TraceStep["tag"], string> = {
  searching: "Searching",
  checking: "Checking",
  found: "Found",
  skipping: "Skipping",
};

/** The same tags on a search that has already finished. */
const TAG_LABEL_PAST: Record<TraceStep["tag"], string> = {
  searching: "Searched",
  checking: "Checked",
  found: "Found",
  skipping: "Skipped",
};

function Row({
  step,
  search,
  newest,
  live,
}: {
  step: TraceStep;
  search: Search;
  newest: boolean;
  live: boolean;
}) {
  return (
    <li
      className="relative animate-[traceIn_320ms_ease-out] pb-5 pl-7"
      style={{ animationFillMode: "backwards" }}
    >
      {/* Timeline rail: the connector stops at the last row. */}
      <span
        aria-hidden="true"
        className="absolute top-4 bottom-0 left-[5px] w-px bg-line-cool"
      />
      <span
        aria-hidden="true"
        className={cx(
          "absolute top-[3px] left-0 block h-[11px] w-[11px] rounded-full border-2 bg-surface-plain",
          newest ? "border-accent-strong" : "border-line-plain",
          newest && live && "animate-[tracePulse_1.8s_ease-out_infinite]",
        )}
      />

      <p
        className={cx(
          "m-0 text-[11px] font-bold tracking-[0.06em] uppercase",
          TAG_STYLE[step.tag],
        )}
      >
        {(live ? TAG_LABEL : TAG_LABEL_PAST)[step.tag]}
      </p>
      <p className="mt-1 mb-2 text-[13px] leading-[1.45] text-ink">
        {narrate(step, search)}
      </p>
      {/*
       * A human name for the call, not the identifier. This used to print
       * `report` / `extract_contact` / `web_search` in a code chip, next to a
       * truncated internal `meta` string ("budget reached: 10 web_search
       * call(s) for this sea…") — our vocabulary leaking into the user's panel.
       * The meta is gone entirely: everything in it that mattered is already in
       * the sentence above, which is where `narrate` puts it.
       */}
      <span className="inline-flex rounded-card bg-paper-deep px-1.5 py-0.5 text-[11px] font-medium text-slate-muted">
        {toolLabel(step.tool)}
      </span>
    </li>
  );
}

/**
 * Mockup 5 — "What I'm doing. Nothing hidden." (past tense once it's done —
 * a finished search narrated in the present reads as if it were still going.)
 *
 * Newest step at the top, dropping in as it arrives. Reverse-chronological
 * because the interesting one is always the latest: the alternative is asking
 * someone to watch the bottom of a growing list.
 *
 * Every row is a call the agent actually made. The backend never synthesises
 * steps to make this look busier, and the sentences are composed only from
 * fields the step really carries — see `lib/trace-narrate.ts`.
 *
 * Below `lg` this panel is a full-width block in the page flow rather than a
 * fixed side column, so the whole step-by-step list would otherwise push the
 * results well down the screen. It opens collapsed to a one-line summary —
 * the same sentence `LiveStatusCard` shows over the map — with a toggle to
 * see every step. At `lg` and up it's always fully expanded: the toggle is
 * hidden there because the column has room for the list already.
 */
export default function TracePanel({
  search,
  headerAccessory,
}: {
  search: Search;
  /** Mobile-only control shown in the header, e.g. the trace⇄results switch —
   * on desktop that switch lives in the shell's column bar instead. */
  headerAccessory?: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const steps = search.steps ?? [];
  const live = search.status === "pending" || search.status === "running";
  // Newest first. The array from the API is chronological; don't mutate it.
  const ordered = [...steps].reverse();
  const summary =
    currentAction(search) ??
    (live ? "Starting up…" : "No steps were recorded for this search.");

  return (
    <div className="flex h-full flex-col">
      <div className="flex-none border-b border-rail-line px-5 pt-[18px] pb-3.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="m-0 text-[15px] font-bold text-ink">
              {live ? "What I'm doing" : "What I did"}
            </h2>
            {/* While the search is live, the map's status card already shows this
                same sentence right above — so only show it here when it isn't
                duplicated (i.e. looking back at a finished search's trace). */}
            {!live && (
              <p className="mt-[3px] mb-0 truncate text-[12px] text-slate-muted lg:hidden">
                {summary}
              </p>
            )}
            <p className="mt-[3px] mb-0 hidden text-[12px] text-slate-muted lg:block">
              {live ? "Live view of every step" : "Every step, in order"}
            </p>
          </div>
          <div className="flex flex-none items-center gap-2 lg:hidden">
            {headerAccessory}
            {ordered.length > 0 && (
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                aria-expanded={expanded}
                className="inline-flex min-h-11 flex-none items-center rounded-pill bg-paper-deep px-3 text-[12px] font-semibold text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
              >
                {expanded ? "Hide steps" : "Show all steps"}
              </button>
            )}
          </div>
        </div>
      </div>

      <div
        className={cx(
          "min-h-0 flex-1 overflow-y-auto px-5 pt-4",
          !expanded && "hidden lg:block",
        )}
      >
        {ordered.length === 0 ? (
          <p className="m-0 text-[12px] leading-normal text-slate-muted">
            {live
              ? "Starting up — the first step appears as soon as I've found places nearby."
              : "No steps were recorded for this search."}
          </p>
        ) : (
          <ul className="m-0 list-none p-0">
            {ordered.map((s, i) => (
              <Row
                key={`${s.at}-${s.tool}`}
                step={s}
                search={search}
                newest={i === 0}
                live={live}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
