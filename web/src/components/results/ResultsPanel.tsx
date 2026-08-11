"use client";

import type { Search, SearchResult } from "@/lib/api";
import Link from "next/link";
import ResultCard from "./ResultCard";

/** Types the agent reports. "pending" rows are companies not yet investigated. */
const GROUPS: Array<{ type: string; label: string }> = [
  { type: "job_listing", label: "Jobs found" },
  { type: "careers_page", label: "Careers pages" },
  { type: "contact_email", label: "Worth emailing" },
];

const KNOWN = new Set(GROUPS.map((g) => g.type));

export function foundResults(search: Search): SearchResult[] {
  return search.results.filter((r) => KNOWN.has(r.opportunity_type));
}

/**
 * The found results in the exact order the panel renders them — grouped by type
 * in GROUPS order. The card's number is its 1-based position here, so the map's
 * numbered pins stay in lockstep with the cards by deriving from the same list.
 */
export function orderedResults(search: Search): SearchResult[] {
  const found = foundResults(search);
  return GROUPS.flatMap((g) =>
    found.filter((r) => r.opportunity_type === g.type),
  );
}

function Header({
  title,
  sub,
  accessory,
}: {
  title: string;
  sub: string;
  /** Mobile-only control (e.g. the trace⇄results switch). */
  accessory?: React.ReactNode;
}) {
  return (
    <div className="flex-none border-b border-rail-line px-5 pt-[18px] pb-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="m-0 text-[15px] font-bold text-ink">{title}</h2>
          <p className="mt-[3px] mb-0 text-[11.5px] text-slate-muted">{sub}</p>
        </div>
        {accessory && (
          <div className="flex flex-none items-center lg:hidden">
            {accessory}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * The results column of mockup 4. Rendered only when there is something to
 * show — the shell drops the whole column otherwise, so an in-flight or empty
 * search doesn't leave a blank gutter next to the map.
 */
export default function ResultsPanel({
  search,
  onHover,
  headerAccessory,
}: {
  search: Search;
  /** Called with a card's place_id on hover/focus (null on leave) so the map
   * can highlight the matching pin. */
  onHover?: (placeId: string | null) => void;
  /** Mobile-only control shown in the header, e.g. the trace⇄results switch. */
  headerAccessory?: React.ReactNode;
}) {
  const found = foundResults(search);

  const grouped = GROUPS.map((g) => ({
    label: g.label,
    items: found.filter((r) => r.opportunity_type === g.type),
  })).filter((g) => g.items.length > 0);

  const inProgress = search.status === "pending" || search.status === "running";

  // Numbering runs across the whole column so a card's number is stable
  // regardless of which group it landed in.
  let n = 0;

  return (
    <div className="flex h-full flex-col">
      <Header
        title={grouped[0]?.label ?? "Results"}
        sub={`${found.length} ${found.length === 1 ? "company" : "companies"} nearby${
          inProgress ? " · still looking" : " · updated just now"
        }`}
        accessory={headerAccessory}
      />

      <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-5 py-4">
        {grouped.map((g, gi) => (
          <section key={g.label} className="flex flex-col gap-3">
            {gi > 0 && (
              <h3 className="m-0 mt-2 text-[11px] font-bold tracking-[0.05em] text-slate-faint uppercase">
                {g.label}
              </h3>
            )}
            {g.items.map((r) => {
              n += 1;
              return (
                <ResultCard
                  key={r.place_id}
                  result={r}
                  index={n}
                  onHover={onHover}
                />
              );
            })}
          </section>
        ))}

        {inProgress && (
          <p className="m-0 px-1 text-[11.5px] leading-normal text-slate-muted">
            More may still appear — I&apos;m working through the rest.
          </p>
        )}

        <Link
          href="/"
          className="mt-2 text-center text-[11.5px] font-semibold no-underline"
        >
          Start another search
        </Link>
      </div>
    </div>
  );
}
