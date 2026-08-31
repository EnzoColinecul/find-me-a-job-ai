"use client";

import type { Me, SearchSummary } from "@/lib/api";
import { logout } from "@/lib/auth";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import AppMark from "../AppMark";
import Avatar from "../Avatar";
import { cx } from "../ui/cx";
import RecentSearches from "./RecentSearches";

function RailLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="m-0 mb-2 px-1 text-[11px] font-bold tracking-[0.05em] text-rail-muted uppercase">
      {children}
    </h2>
  );
}

/**
 * Mockup 3's left rail: 216px, paper-white, history at the top and who you are
 * pinned to the bottom.
 *
 * Below `lg` the same markup collapses to a **one-line header**: the mark, the
 * primary action, and a disclosure for the history and account block. It used
 * to render as a full column at the very bottom of the page, which on a phone
 * put "New search" roughly 4000px below the results the user was reading.
 *
 * There is deliberately no second copy of the button for mobile — one DOM node
 * reordered by flexbox, so the two layouts can't drift apart.
 */
export default function Rail({
  me,
  recent,
  loadingRecent,
  onNewSearch,
  newSearchDisabledReason,
}: {
  me: Me;
  recent: SearchSummary[];
  loadingRecent: boolean;
  onNewSearch: () => void;
  /**
   * Set once the free search is spent. The button is the door to the free-text
   * step, and that step calls `POST /roles/interpret` — a paid LLM call on a
   * request that can only end in a 402. Closing the door is cheaper than
   * apologising after it.
   */
  newSearchDisabledReason?: string | null;
}) {
  const blocked = Boolean(newSearchDisabledReason);
  const [open, setOpen] = useState(false);

  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-2.5 lg:h-full lg:min-h-0 lg:flex-col lg:flex-nowrap lg:items-stretch lg:gap-0 lg:py-4">
      <AppMark size={24} className="flex-none px-1 lg:pb-4" />

      <button
        type="button"
        onClick={onNewSearch}
        disabled={blocked}
        aria-describedby={blocked ? "new-search-blocked" : undefined}
        className="flex min-h-11 flex-1 items-center justify-center gap-2 rounded-panel border border-line-cool bg-surface-plain px-3 py-2.5 text-[13px] font-semibold text-ink shadow-card transition-colors duration-150 hover:border-line-plain focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong disabled:cursor-not-allowed disabled:border-line-cool disabled:text-slate-muted disabled:shadow-none disabled:hover:border-line-cool lg:flex-none lg:justify-start"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M12 5v14M5 12h14"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
          />
        </svg>
        New search
      </button>

      {/* The disclosure for everything below — phone only; at lg the column has
          room for all of it at once. */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="rail-details"
        className="flex h-11 w-11 flex-none items-center justify-center rounded-card text-ink-soft transition-colors duration-150 hover:bg-rail-active focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong lg:hidden"
      >
        <span className="sr-only">
          {open ? "Hide recent searches and account" : "Recent searches and account"}
        </span>
        <ChevronDown
          aria-hidden="true"
          strokeWidth={2.2}
          className={cx(
            "h-[18px] w-[18px] flex-none transition-transform duration-150",
            open && "rotate-180",
          )}
        />
      </button>

      {/* Outside the disclosure on purpose: it is the button's
          `aria-describedby` target, and a display:none description is not
          announced. It also has to be readable at the moment the button is
          refusing, not one tap later. */}
      {blocked && (
        <p
          id="new-search-blocked"
          className="m-0 w-full px-1 text-[12px] leading-snug text-rail-muted lg:mt-1.5"
        >
          {newSearchDisabledReason}
        </p>
      )}

      <div
        id="rail-details"
        className={cx(
          "w-full min-w-0 flex-col lg:flex lg:min-h-0 lg:flex-1",
          open ? "flex" : "hidden",
        )}
      >
        {/* Recent searches stay live either way — looking at a search you've
            already paid for is not a new one. */}
        <div className="mt-4 flex min-h-0 flex-col lg:mt-[22px] lg:flex-1">
          <RailLabel>Recent searches</RailLabel>
          {/*
           * The only scrolling region in the rail. It takes the leftover
           * height at >=lg, which is also what pins the account block to the
           * bottom — so there is no spacer element here any more. Below lg the
           * rail is a disclosure in a page that scrolls on its own, so the
           * list just grows.
           */}
          <div className="min-h-0 lg:flex-1 lg:overflow-y-auto">
            <RecentSearches searches={recent} loading={loadingRecent} />
          </div>
        </div>

        <div className="mt-4 flex-none border-t border-rail-line pt-3 lg:mt-4">
          <div className="flex items-center gap-2.5 px-1 py-1.5">
            <Avatar me={me} tone="accent" size={28} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-semibold text-ink">
                {me.name || "You"}
              </div>
              <div className="truncate text-[12px] text-rail-muted">
                {me.email}
              </div>
            </div>
          </div>
          <p className="m-0 px-1 text-[12px] text-rail-muted">
            {me.free_search_used
              ? "Free search used"
              : "1 free search available"}
          </p>
          <button
            type="button"
            onClick={() => logout()}
            className="mt-1.5 inline-flex min-h-11 items-center rounded-card px-1 py-1 text-[12px] font-medium text-ink-soft hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
