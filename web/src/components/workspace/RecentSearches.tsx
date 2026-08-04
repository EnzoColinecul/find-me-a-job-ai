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

function PinIcon({ className }: { className?: string }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
    >
      <path
        d="M12 2C7 2 3 6 3 11c0 7 9 11 9 11s9-4 9-11c0-5-4-9-9-9z"
        fill="currentColor"
      />
    </svg>
  );
}

export default function RecentSearches({
  searches,
  loading,
}: {
  searches: SearchSummary[];
  loading: boolean;
}) {
  if (loading) {
    return <p className="m-0 px-2.5 text-[12.5px] text-rail-muted">Loading…</p>;
  }

  if (searches.length === 0) {
    return (
      <p className="m-0 px-2.5 text-[12.5px] leading-normal text-rail-muted">
        Nothing here yet. Your searches will appear as you run them.
      </p>
    );
  }

  return (
    <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
      {searches.map((s) => (
        <li key={s.search_id}>
          <Link
            href={`/search/${s.search_id}`}
            className="flex items-center gap-2 rounded-card px-2.5 py-2 text-[12.5px] font-medium text-ink-soft no-underline hover:bg-rail-active"
          >
            <PinIcon className="flex-none text-rail-muted" />
            <span className="truncate">
              {titleCase(s.roles.join(", ") || "Search")} ·{" "}
              {shortPlace(s.location_label, s.lat, s.lng)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
