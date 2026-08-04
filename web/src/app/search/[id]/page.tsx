"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";
import { getMe, getSearch, stopSearch, type Me, type Search } from "@/lib/api";
import WorkspaceShell from "@/components/workspace/WorkspaceShell";
import { MapBar, SearchGlyph, StatusPill } from "@/components/workspace/MapBar";
import ResultsPanel, { foundResults } from "@/components/results/ResultsPanel";
import TracePanel from "@/components/results/TracePanel";

const POLL_MS = 3000;

function titleCase(s: string): string {
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

function Centred({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-dvh items-center justify-center px-5">
      <div className="max-w-[46ch] text-center">{children}</div>
    </main>
  );
}

/**
 * Mockup 4 — the same shell as the workspace with the results column open.
 *
 * Results are not a separate page: the map stays on screen so you can see where
 * the search was centred while you read what came back.
 */
export default function SearchPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [search, setSearch] = useState<Search | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showTrace, setShowTrace] = useState(true);
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);

  useEffect(() => {
    getMe()
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

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
        } else {
          // Finished: the trace has served its purpose, so hand the panel over
          // to the results. The user can switch back to it.
          setShowTrace(false);
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
      <Centred>
        <p role="alert" className="m-0 mb-3 text-sm text-pin">
          {error}
        </p>
        <Link href="/" className="text-[13px] font-semibold">
          ← New search
        </Link>
      </Centred>
    );

  if (!search || !me)
    return (
      <Centred>
        <p className="text-sm text-slate-muted">Loading…</p>
      </Centred>
    );

  const inProgress = search.status === "pending" || search.status === "running";
  const found = foundResults(search);
  const place =
    search.params.location_label ||
    `${search.params.lat.toFixed(3)}, ${search.params.lng.toFixed(3)}`;

  // Defaulted, not assumed: an API that predates the trace work (or a stale
  // local uvicorn) returns neither field, and destructuring undefined here would
  // blank the whole page instead of just hiding the progress line.
  const { done, total } = search.progress ?? { done: 0, total: 0 };
  const steps = search.steps ?? [];
  const status: { tone: "working" | "done" | "failed"; text: string } =
    inProgress
      ? {
          tone: "working",
          text: total
            ? `Looking at ${Math.min(done + 1, total)} of ${total} places nearby…`
            : "Finding places nearby…",
        }
      : search.status === "failed"
        ? { tone: "failed", text: "This search didn't finish" }
        : search.status === "cancelled"
          ? {
              tone: "done",
              text: `Stopped — ${found.length} ${found.length === 1 ? "place" : "places"} found before you stopped`,
            }
          : {
              tone: "done",
              text:
                found.length === 0
                  ? "Search complete — nothing worth contacting"
                  : `Search complete — ${found.length} ${found.length === 1 ? "place" : "places"} worth contacting`,
            };

  const hasResults = found.length > 0;
  // While it runs, the trace is the panel. Afterwards the results are, unless
  // the user asks to see the working. Either way, no findings and no steps
  // means no column at all rather than an empty gutter beside the map.
  const showingTrace = showTrace && (inProgress || steps.length > 0);
  const panel = showingTrace ? (
    <TracePanel
      search={search}
      stopping={stopping}
      stopError={stopError}
      onStop={async () => {
        setStopping(true);
        setStopError(null);
        try {
          await stopSearch(id);
          setSearch((s) => (s ? { ...s, status: "cancelled" } : s));
        } catch (e) {
          setStopError(e instanceof Error ? e.message : String(e));
        } finally {
          setStopping(false);
        }
      }}
    />
  ) : hasResults ? (
    <ResultsPanel search={search} />
  ) : undefined;

  return (
    <WorkspaceShell
      me={me}
      center={{ lat: search.params.lat, lng: search.params.lng }}
      radiusKm={search.params.radius_km}
      onNewSearch={() => router.push("/")}
      rightPanelTitle={showingTrace ? "What I'm doing" : "Results"}
      rightPanel={panel}
      rightPanelSwitch={
        // Only offer the swap when both views have something in them.
        hasResults && steps.length > 0 ? (
          <button
            type="button"
            onClick={() => setShowTrace((v) => !v)}
            className="rounded-pill px-2 py-0.5 text-[11px] font-semibold text-slate-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
          >
            {showingTrace
              ? `Results (${found.length})`
              : "See what I did"}
          </button>
        ) : undefined
      }
      topBar={
        <MapBar>
          <SearchGlyph />
          <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-ink">
            {titleCase(search.params.roles.join(", "))} · {place} ·{" "}
            {search.params.radius_km} km
          </span>
          <Link
            href="/"
            className="flex-none rounded-pill bg-paper-deep px-3 py-[5px] text-[11.5px] font-semibold text-ink no-underline transition-colors duration-150 hover:bg-line-soft"
          >
            Refine
          </Link>
        </MapBar>
      }
      mapOverlay={
        <>
          <StatusPill tone={status.tone}>{status.text}</StatusPill>

          {/* A failed search must never read like an empty one. */}
          {search.status === "failed" && (
            <div className="absolute right-5 bottom-20 left-5 rounded-panel border border-pin/40 bg-surface-plain px-4 py-3 shadow-float lg:left-auto lg:w-[330px]">
              <strong className="text-[13px] text-ink">
                Something went wrong with this search.
              </strong>
              <p className="mt-1 mb-0 text-[11.5px] leading-normal text-slate-muted">
                It didn&apos;t finish, so this isn&apos;t a &quot;nothing
                found&quot; answer. Please try again — if it keeps happening,
                the problem is on our side.
              </p>
            </div>
          )}

          {/* Stopped is the user's own choice — not an error, not "no results". */}
          {search.status === "cancelled" && found.length === 0 && (
            <div className="absolute right-5 bottom-20 left-5 rounded-panel bg-surface-plain px-4 py-3.5 shadow-float lg:left-auto lg:w-[330px]">
              <strong className="text-[13px] text-ink">
                You stopped this search
              </strong>
              <p className="mt-1 mb-2 text-[11.5px] leading-normal text-slate-muted">
                Nothing had turned up yet when it stopped. The steps I got
                through are still on the right.
              </p>
              <Link href="/" className="text-[11.5px] font-semibold">
                Start another search →
              </Link>
            </div>
          )}

          {search.status === "completed" && found.length === 0 && (
            <div className="absolute right-5 bottom-20 left-5 rounded-panel bg-surface-plain px-4 py-3.5 shadow-float lg:left-auto lg:w-[330px]">
              <strong className="text-[13px] text-ink">
                Nothing worth contacting within {search.params.radius_km} km
              </strong>
              <p className="mt-1 mb-2 text-[11.5px] leading-normal text-slate-muted">
                I checked every business I could find and none had an opening or
                a way in. A wider radius or a different role usually turns
                something up.
              </p>
              <Link href="/" className="text-[11.5px] font-semibold">
                Try another search →
              </Link>
            </div>
          )}
        </>
      }
    />
  );
}
