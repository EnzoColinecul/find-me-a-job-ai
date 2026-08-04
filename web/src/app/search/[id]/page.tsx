"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { getSearch, type Search } from "@/lib/api";
import { Button, Card } from "@/components/ui";

// NOTE: this is a token migration only — the full results redesign
// (source-labelled links, Copy buttons, the new card layout) is its own
// Phase 5 card: "Results panel restyle + source-labelled links".

const POLL_MS = 3000;
const LABELS: Record<string, string> = {
  job_listing: "🎯 Job listings",
  careers_page: "💼 Careers pages",
  contact_email: "✉️ Contact emails",
};

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto max-w-180 px-4 py-12">{children}</main>;
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
        <p role="alert" className="m-0 mb-4 text-sm text-pin">
          {error}
        </p>
        <Link href="/" className="text-sm font-semibold">
          ← New search
        </Link>
      </Shell>
    );

  if (!search)
    return (
      <Shell>
        <p className="m-0 text-sm text-slate-muted">Loading…</p>
      </Shell>
    );

  const inProgress = search.status === "pending" || search.status === "running";
  const found = search.results.filter((r) => LABELS[r.opportunity_type]);
  const grouped = Object.entries(LABELS)
    .map(([type, label]) => ({
      label,
      items: found.filter((r) => r.opportunity_type === type),
    }))
    .filter((g) => g.items.length > 0);

  return (
    <Shell>
      <Link href="/" className="text-[13px] font-semibold">
        ← New search
      </Link>

      <h1 className="mt-4 mb-1 text-2xl font-extrabold text-ink">Results</h1>
      <p className="m-0 mb-8 text-sm text-slate-muted">
        {search.params.roles.join(", ")} · {search.params.radius_km} km radius
      </p>

      {inProgress && (
        <Card className="mb-8 px-4 py-3 text-sm text-slate-muted">
          ⏳ Investigating companies… {search.total} checked so far. Results appear
          as they&apos;re found.
        </Card>
      )}

      {grouped.map((g) => (
        <section key={g.label} className="mb-8">
          <h2 className="m-0 mb-3 text-[15px] font-bold text-ink">{g.label}</h2>
          <div className="grid gap-2.5">
            {g.items.map((r) => (
              <Card key={r.place_id} className="px-4 py-3.5">
                <strong className="text-sm text-ink">{r.company}</strong>
                <div className="mt-0.5 text-[13px] text-slate-muted">
                  {r.address}
                </div>
                {r.links.map((l) => (
                  <div key={l} className="mt-1.5 truncate text-[13px]">
                    <a href={l} target="_blank" rel="noreferrer noopener">
                      {l}
                    </a>
                  </div>
                ))}
                {r.emails.map((m) => (
                  <div key={m} className="mt-1.5 flex items-center gap-2">
                    <code className="rounded-tag bg-paper-deep px-1.5 py-0.5 text-[13px] text-ink">
                      {m}
                    </code>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => navigator.clipboard.writeText(m)}
                    >
                      Copy
                    </Button>
                  </div>
                ))}
              </Card>
            ))}
          </div>
        </section>
      ))}

      {search.status === "failed" && (
        <Card className="border-pin/40 bg-pin/6 px-4 py-3.5">
          <strong className="text-sm text-ink">
            Something went wrong with this search.
          </strong>
          <p className="mt-1.5 mb-0 text-[13px] text-slate-muted">
            It didn&apos;t finish, so this isn&apos;t a &quot;no results&quot;
            answer. Please try again — if it keeps happening, the problem is on our
            side.
          </p>
        </Card>
      )}

      {search.status === "completed" && found.length === 0 && (
        <p className="text-sm text-slate-muted">
          No job opportunities were found within the selected search radius. Try a
          larger radius or different roles.
        </p>
      )}
    </Shell>
  );
}
