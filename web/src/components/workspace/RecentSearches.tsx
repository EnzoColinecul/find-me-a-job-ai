"use client";

import type { SearchSummary } from "@/lib/api";
import Link from "next/link";
import { usePathname } from "next/navigation";

function titleCase(s: string): string {
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

/** "Surry Hills NSW 2010" → "Surry Hills". The rail has no room for the rest. */
function shortPlace(label: string, lat: number, lng: number): string {
  const first = label.split(",")[0]?.trim();
  if (first)
    return first.replace(/\s+(NSW|VIC|QLD|WA|SA|TAS|NT|ACT)\s*\d{4}$/i, "");
  return `${lat.toFixed(3)}, ${lng.toFixed(3)}`;
}

export default function RecentSearches({
  searches,
  loading,
}: {
  searches: SearchSummary[];
  loading: boolean;
}) {
  /*
   * The open search comes from the URL, not from a click handler: the rail is
   * remounted on every navigation (and on a hard load of /search/<id> there was
   * no click at all), so any state we set on click is gone by the time the row
   * needs to look selected.
   */
  const pathname = usePathname();
  const activeId = pathname?.match(/^\/search\/([^/?#]+)/)?.[1] ?? null;

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
      {searches.map((s) => {
        const active = s.search_id === activeId;
        return (
          <li key={s.search_id}>
            <Link
              href={`/search/${s.search_id}`}
              aria-current={active ? "page" : undefined}
              className={[
                "flex min-h-11 items-center gap-2 rounded-card px-1 py-2 text-[12.5px] no-underline transition-colors duration-150",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong",
                active
                  ? "bg-rail-active font-semibold text-accent-strong"
                  : "font-medium text-ink-soft hover:bg-rail-active",
              ].join(" ")}
            >
              <span className="truncate">
                {titleCase(s.roles.join(", ") || "Search")} ·{" "}
                {shortPlace(s.location_label, s.lat, s.lng)}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
