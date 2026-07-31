"use client";

import { use, useEffect, useState } from "react";
import { getSearch, type Search } from "@/lib/api";

const POLL_MS = 3000;
const LABELS: Record<string, string> = {
  job_listing: "🎯 Job listings",
  careers_page: "💼 Careers pages",
  contact_email: "✉️ Contact emails",
};

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
      <main style={{ maxWidth: 720, margin: "3rem auto", padding: "0 1rem" }}>
        <p style={{ color: "crimson" }}>{error}</p>
        <a href="/">← New search</a>
      </main>
    );
  if (!search)
    return (
      <main style={{ maxWidth: 720, margin: "3rem auto", padding: "0 1rem" }}>
        <p>Loading…</p>
      </main>
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
    <main style={{ maxWidth: 720, margin: "3rem auto", padding: "0 1rem" }}>
      <a href="/">← New search</a>
      <h1>Results</h1>
      <p style={{ color: "#666" }}>
        {search.params.roles.join(", ")} · {search.params.radius_km} km radius
      </p>

      {inProgress && (
        <p>
          ⏳ Investigating companies… {search.total} checked so far. Results appear as
          they’re found.
        </p>
      )}

      {grouped.map((g) => (
        <section key={g.label}>
          <h2>{g.label}</h2>
          {g.items.map((r) => (
            <div
              key={r.place_id}
              style={{
                border: "1px solid #ddd",
                borderRadius: 8,
                padding: "0.8rem",
                marginBottom: "0.6rem",
              }}
            >
              <strong>{r.company}</strong>
              <div style={{ color: "#666", fontSize: "0.9rem" }}>{r.address}</div>
              {r.links.map((l) => (
                <div key={l}>
                  <a href={l} target="_blank" rel="noreferrer noopener">
                    {l}
                  </a>
                </div>
              ))}
              {r.emails.map((m) => (
                <div key={m}>
                  <code>{m}</code>{" "}
                  <button onClick={() => navigator.clipboard.writeText(m)}>copy</button>
                </div>
              ))}
            </div>
          ))}
        </section>
      ))}

      {!inProgress && found.length === 0 && (
        <p>
          No job opportunities were found within the selected search radius. Try a
          larger radius or different roles.
        </p>
      )}
    </main>
  );
}
