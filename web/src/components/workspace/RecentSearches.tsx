"use client";

import type { SearchSummary } from "@/lib/api";
import Link from "next/link";
import { usePathname } from "next/navigation";

function titleCase(s: string): string {
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Does this label look like a coordinate pair rather than a place?
 *
 * `location_label` is whatever the workspace could name the point at search
 * time, and `useReverseGeocode` deliberately falls back to `formatLatLng` when
 * the lookup fails — which it does for every pin dropped on the map until the
 * **Geocoding API is enabled on the browser key** (see the warning in
 * `useReverseGeocode.ts`; it's a manual GCP console step). Those searches were
 * saved with "-37.81569, 144.96328" as their label, and the rail then split on
 * the comma and showed half a coordinate: "Software Engineer · -37.81569".
 *
 * Enabling the API fixes new searches; this fixes the ones already saved, and
 * every future failed lookup.
 */
function isCoordinateLabel(label: string): boolean {
  return /^\s*-?\d{1,3}(\.\d+)?\s*,\s*-?\d{1,3}(\.\d+)?\s*$/.test(label);
}

/** "Surry Hills NSW 2010" → "Surry Hills". The rail has no room for the rest. */
function shortPlace(label: string): string {
  if (!label.trim() || isCoordinateLabel(label)) return "Pinned location";
  const first = label.split(",")[0]?.trim();
  if (!first) return "Pinned location";
  const trimmed = first.replace(
    /\s+(NSW|VIC|QLD|WA|SA|TAS|NT|ACT)\s*\d{4}$/i,
    "",
  );
  // A first segment that is itself just a number ("-37.81569", or a street
  // number that lost its street) tells the user nothing.
  return /^-?\d+(\.\d+)?$/.test(trimmed) ? "Pinned location" : trimmed;
}

/**
 * "Today" / "Yesterday" / "27 Aug" / "27 Aug 2025".
 *
 * Ten rows that all read "Software Engineer · Melbourne" are indistinguishable;
 * the date is the cheapest thing that separates them. (A result count would be
 * better still, but `GET /searches` reads the owner-index item, which doesn't
 * carry one — that needs an API change.)
 */
function shortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";

  const startOfDay = (x: Date) =>
    new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const now = new Date();
  const days = Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);

  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    ...(d.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
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
    return <p className="m-0 px-2.5 text-[12px] text-rail-muted">Loading…</p>;
  }

  if (searches.length === 0) {
    return (
      <p className="m-0 px-2.5 text-[12px] leading-normal text-rail-muted">
        Nothing here yet. Your searches will appear as you run them.
      </p>
    );
  }

  return (
    <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
      {searches.map((s) => {
        const active = s.search_id === activeId;
        const place = shortPlace(s.location_label);
        const when = shortDate(s.created_at);
        return (
          <li key={s.search_id}>
            <Link
              href={`/search/${s.search_id}`}
              aria-current={active ? "page" : undefined}
              className={[
                "flex min-h-11 flex-col justify-center gap-px rounded-card px-1 py-2 no-underline transition-colors duration-150",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong",
                active
                  ? "bg-rail-active font-semibold text-accent-deep"
                  : "font-medium text-ink-soft hover:bg-rail-active",
              ].join(" ")}
            >
              <span className="truncate text-[13px] leading-tight">
                {titleCase(s.roles.join(", ") || "Search")}
              </span>
              <span
                className={[
                  "truncate text-[12px] leading-tight font-normal",
                  active ? "text-ink-soft" : "text-rail-muted",
                ].join(" ")}
              >
                {place}
                {when && ` · ${when}`}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
