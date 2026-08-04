"use client";

import Image from "next/image";
import Link from "next/link";
import { use, useEffect, useState } from "react";
import { getSearch, type Search } from "@/lib/api";
import ResultCard from "@/components/results/ResultCard";
import { Button, Card } from "@/components/ui";

const POLL_MS = 3000;

/** Types the agent reports. "pending" rows are companies not yet investigated. */
const GROUPS: Array<{ type: string; label: string }> = [
  { type: "job_listing", label: "Jobs found" },
  { type: "careers_page", label: "Careers pages" },
  { type: "contact_email", label: "Worth emailing" },
];

function titleCase(s: string): string {
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh px-4 py-6 sm:px-6">
      <div className="mx-auto max-w-[760px]">{children}</div>
    </div>
  );
}

export default function SearchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [search, setSearch] = useState<Search | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;

    const poll = async () => {
      try {
        const s = await getSearch(id);
        if (stopped) return;
        setSearch(s);
        if (s.status === "pending" || s.status === "running") {
          timer = setTimeout(poll, POLL_MS);
        }
      } catch (e) {
        if (!stopped) setError(e instanceof Error ? e.message : String(e));
      }
    };
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [id]);

  if (error)
    return (
      <Shell>
        <Card className="px-4 py-4">
          <p role="alert" className="m-0 mb-3 text-sm text-pin">
            {error}
          </p>
          <Link href="/" className="text-[13px] font-semibold">
            ← New search
          </Link>
        </Card>
      </Shell>
    );

  if (!search)
    return (
      <Shell>
        <p className="text-sm text-slate-muted">Loading…</p>
      </Shell>
    );

  const inProgress = search.status === "pending" || search.status === "running";
  const known = new Set(GROUPS.map((g) => g.type));
  const found = search.results.filter((r) => known.has(r.opportunity_type));
  const grouped = GROUPS.map((g) => ({
    label: g.label,
    items: found.filter((r) => r.opportunity_type === g.type),
  })).filter((g) => g.items.length > 0);

  const place =
    search.params.location_label ||
    `${search.params.lat.toFixed(3)}, ${search.params.lng.toFixed(3)}`;

  const statusLine = inProgress
    ? `Looking at ${search.total} ${search.total === 1 ? "place" : "places"} nearby…`
    : search.status === "completed"
      ? found.length === 0
        ? "Search complete — nothing worth contacting this time"
        : `Search complete — ${found.length} ${found.length === 1 ? "place" : "places"} worth contacting`
      : "This search didn't finish";

  return (
    <Shell>
      {/* Header: what was searched, and a way back to change it */}
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <Image
          src="/logo.png"
          alt=""
          width={28}
          height={28}
          priority
          className="h-7 w-7 flex-none object-contain"
        />
        <div className="min-w-0 flex-1">
          <h1 className="m-0 truncate text-[15px] font-bold text-ink">
            {titleCase(search.params.roles.join(", "))} · {place} ·{" "}
            {search.params.radius_km} km
          </h1>
          <p
            className="m-0 text-[13px] text-slate-muted"
            aria-live="polite"
          >
            {statusLine}
          </p>
        </div>
        <Link href="/">
          <Button variant="secondary" size="sm">
            Refine
          </Button>
        </Link>
      </header>

      {grouped.map((g) => (
        <section key={g.label} className="mb-7">
          <h2 className="m-0 mb-1 text-[15px] font-bold text-ink">{g.label}</h2>
          <p className="m-0 mb-3 text-[12px] text-slate-muted">
            {g.items.length} {g.items.length === 1 ? "company" : "companies"}{" "}
            nearby
          </p>
          <div className="grid gap-2.5">
            {g.items.map((r) => (
              <ResultCard key={r.place_id} result={r} />
            ))}
          </div>
        </section>
      ))}

      {inProgress && (
        <Card className="px-4 py-3.5 text-[13px] text-slate-muted">
          Results appear here as I find them. This usually takes a minute or two.
        </Card>
      )}

      {/* A failed search must never look like an empty one — that hides breakage. */}
      {search.status === "failed" && (
        <Card className="border-pin/40 bg-pin/6 px-4 py-4">
          <strong className="text-sm text-ink">
            Something went wrong with this search.
          </strong>
          <p className="mt-1.5 mb-0 text-[13px] leading-normal text-slate-muted">
            It didn&apos;t finish, so this isn&apos;t a &quot;no results&quot;
            answer. Please try again — if it keeps happening, the problem is on
            our side.
          </p>
        </Card>
      )}

      {search.status === "completed" && found.length === 0 && (
        <Card className="px-5 py-6 text-center">
          <p className="m-0 mb-1 text-sm font-semibold text-ink">
            Nothing worth contacting within {search.params.radius_km} km
          </p>
          <p className="mx-auto m-0 mb-4 max-w-[42ch] text-[13px] leading-normal text-slate-muted">
            I checked every business I could find and none had an opening or a
            way in. A wider radius or a different role usually turns something
            up.
          </p>
          <Link href="/">
            <Button size="sm">Try another search</Button>
          </Link>
        </Card>
      )}
    </Shell>
  );
}
