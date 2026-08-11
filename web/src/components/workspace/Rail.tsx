"use client";

import type { Me, SearchSummary } from "@/lib/api";
import { logout } from "@/lib/auth";
import AppMark from "../AppMark";
import Avatar from "../Avatar";
import RecentSearches from "./RecentSearches";

function RailLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="m-0 mb-2 px-1 text-[10.5px] font-bold tracking-[0.05em] text-rail-muted uppercase">
      {children}
    </h2>
  );
}

/**
 * Mockup 3's left rail: 216px, paper-white, history at the top and who you are
 * pinned to the bottom. On narrow screens the workspace renders this as a
 * normal block instead of a fixed column.
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

  return (
    <div className="flex h-full flex-col gap-0 px-3 py-4">
      <AppMark size={24} className="px-1 pb-4" />

      <button
        type="button"
        onClick={onNewSearch}
        disabled={blocked}
        aria-describedby={blocked ? "new-search-blocked" : undefined}
        className="flex min-h-11 items-center gap-2 rounded-panel border border-line-cool bg-surface-plain px-3 py-2.5 text-[13px] font-semibold text-ink shadow-card transition-colors duration-150 hover:border-line-plain focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong disabled:cursor-not-allowed disabled:border-line-cool disabled:text-slate-faint disabled:shadow-none disabled:hover:border-line-cool"
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

      {blocked && (
        <p
          id="new-search-blocked"
          className="m-0 mt-1.5 px-1 text-[11px] leading-snug text-rail-muted"
        >
          {newSearchDisabledReason}
        </p>
      )}

      {/* Recent searches stay live either way — looking at a search you've
          already paid for is not a new one. */}
      <div className="mt-[22px]">
        <RailLabel>Recent searches</RailLabel>
        <RecentSearches searches={recent} loading={loadingRecent} />
      </div>

      <div className="flex-1" />

      <div className="mt-6 border-t border-rail-line pt-3">
        <div className="flex items-center gap-2.5 px-1 py-1.5">
          <Avatar me={me} tone="accent" size={28} />
          <div className="min-w-0 flex-1">
            <div className="truncate text-[12.5px] font-semibold text-ink">
              {me.name || "You"}
            </div>
            <div className="truncate text-[11px] text-rail-muted">
              {me.email}
            </div>
          </div>
        </div>
        <p className="m-0 px-1 text-[11px] text-rail-muted">
          {me.free_search_used ? "Free search used" : "1 free search available"}
        </p>
        <button
          type="button"
          onClick={() => logout()}
          className="mt-1.5 inline-flex min-h-11 items-center rounded-card px-1 py-1 text-[11.5px] font-medium text-ink-soft hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
