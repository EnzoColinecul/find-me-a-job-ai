"use client";

import Link from "next/link";
import type { SearchSummary } from "@/lib/api";

function titleCase(s: string): string {
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

/** "Surry Hills NSW 2010" → "Surry Hills". The rail has no room for the rest. */
function shortPlace(label: string, lat: number, lng: number): string {
  const first = label.split(",")[0]?.trim();
  if (first) return first.replace(/\s+(NSW|VIC|QLD|WA|SA|TAS|NT|ACT)\s*\d{4}$/i, "");
  return `${lat.toFixed(3)}, ${lng.toFixed(3)}`;
}

export default function RecentSearches({
  searches,
  loading,
}: {
  searches: SearchSummary[];
  loading: boolean;
}) {
  if (loading) {
    return <p className="m-0 text-[13px] text-slate-muted">Loading…</p>;
  }

  if (searches.length === 0) {
    return (
      <p className="m-0 text-[13px] leading-normal text-slate-muted">
        Nothing here yet. Your searches will appear as you run them.
      </p>
    );
  }

  return (
    <ul className="m-0 grid list-none gap-0.5 p-0">
      {searches.map((s) => (
        <li key={s.search_id}>
          <Link
            href={`/search/${s.search_id}`}
            className="block truncate rounded-card px-2 py-1.5 text-[13px] text-ink no-underline hover:bg-paper-deep"
          >
            {titleCase(s.roles.join(", ") || "Search")} ·{" "}
            <span className="text-slate-muted">
              {shortPlace(s.location_label, s.lat, s.lng)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
