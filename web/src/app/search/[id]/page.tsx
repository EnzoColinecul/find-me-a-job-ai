"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";
import { getMe, getSearch, stopSearch, type Me, type Search } from "@/lib/api";
import WorkspaceShell from "@/components/workspace/WorkspaceShell";
import { MapBar, SearchGlyph, StatusPill } from "@/components/workspace/MapBar";
import ResultsPanel, {
  foundResults,
  orderedResults,
} from "@/components/results/ResultsPanel";
import TracePanel from "@/components/results/TracePanel";
import LiveStatusCard, {
  MapActivityPing,
} from "@/components/results/LiveStatusCard";

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
  /** place_id of the result card being hovered/focused, to highlight its pin. */
  const [hoveredPin, setHoveredPin] = useState<string | null>(null);

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

  // Refine reopens the workspace with this search's parameters prefilled, so the
  // user tweaks the last search rather than starting from a blank map. The role
  // labels, centre, radius and place name are all we have (and all we need); the
  // workspace re-derives curated keys from the labels.
  const refineHref = (() => {
    const q = new URLSearchParams();
    search.params.roles.forEach((r) => q.append("role", r));
    q.set("lat", String(search.params.lat));
    q.set("lng", String(search.params.lng));
    q.set("radius", String(search.params.radius_km));
    if (search.params.location_label)
      q.set("loc", search.params.location_label);
    return `/?${q.toString()}`;
  })();

  // Defaulted, not assumed: an API that predates the trace work (or a stale
  // local uvicorn) doesn't send `steps`, and reading .length off undefined would
  // blank the whole page. (`progress` is read by LiveStatusCard, defended there.)
  const steps = search.steps ?? [];
  // While it runs, LiveStatusCard owns the map overlay; the pill only reports
  // finished states, so the two can never contradict each other.
  const status: { tone: "done" | "failed"; text: string } | null = inProgress
    ? null
    : search.status === "failed"
      ? { tone: "failed" as const, text: "This search didn't finish" }
      : search.status === "cancelled"
        ? {
            tone: "done" as const,
            text: `Stopped — ${found.length} ${found.length === 1 ? "place" : "places"} found before you stopped`,
          }
        : {
            tone: "done" as const,
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
  const stop = async () => {
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
  };

  // The trace⇄results switch. One node, rendered in the shell's column bar on
  // desktop and inside the panel header on mobile (where the bar is hidden), so
  // it never sits in a near-empty strip of its own.
  //
  // The two directions aren't equal: getting *to the results* is the thing a
  // user must never miss, so that direction is a solid accent button with a
  // chevron — an obvious tap target — while the way back to the working is a
  // quiet text link. A muted "Results (9)" read as a stat, not a button.
  const viewSwitch =
    hasResults && steps.length > 0 ? (
      showingTrace ? (
        <button
          type="button"
          onClick={() => setShowTrace(false)}
          className="inline-flex min-h-11 flex-none items-center gap-1 rounded-pill bg-accent-strong pr-2.5 pl-3.5 text-[12px] font-semibold text-white transition-opacity duration-150 hover:opacity-95 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
        >
          See results ({found.length})
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            aria-hidden="true"
            className="flex-none"
          >
            <path
              d="M9 6l6 6-6 6"
              stroke="currentColor"
              strokeWidth="2.4"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setShowTrace(true)}
          className="inline-flex min-h-11 flex-none items-center rounded-pill px-2.5 text-[11px] font-semibold text-slate-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
        >
          See what I did
        </button>
      )
    ) : null;

  const panel = showingTrace ? (
    <TracePanel search={search} headerAccessory={viewSwitch} />
  ) : hasResults ? (
    <ResultsPanel
      search={search}
      onHover={setHoveredPin}
      headerAccessory={viewSwitch}
    />
  ) : undefined;

  // Numbered pins for the results, in the same order the cards are numbered.
  // Results without coordinates (older/expired searches, or a pre-pin backend)
  // are skipped — the map simply doesn't place them, cards are unaffected.
  const markers = orderedResults(search).flatMap((r, i) =>
    typeof r.lat === "number" && typeof r.lng === "number"
      ? [
          {
            id: r.place_id,
            position: { lat: r.lat, lng: r.lng },
            index: i + 1,
            featured: i === 0,
          },
        ]
      : [],
  );

  return (
    <WorkspaceShell
      me={me}
      center={{ lat: search.params.lat, lng: search.params.lng }}
      radiusKm={search.params.radius_km}
      markers={markers}
      highlightedMarkerId={hoveredPin}
      onNewSearch={() => router.push("/")}
      /* Same wording as `/`, so the rail doesn't offer here what it refuses
         one screen over. */
      newSearchDisabledReason={
        me.free_search_used
          ? "You've used your free search. Your past results are still here in the rail."
          : null
      }
      rightPanelTitle={showingTrace ? "What I'm doing" : "Results"}
      rightPanel={panel}
      rightPanelSwitch={viewSwitch}
      topBar={
        <MapBar>
          <SearchGlyph />
          <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-ink">
            {titleCase(search.params.roles.join(", "))} · {place} ·{" "}
            {search.params.radius_km} km
          </span>
          {inProgress ? (
            <button
              type="button"
              onClick={stop}
              disabled={stopping}
              className="inline-flex min-h-11 flex-none items-center rounded-pill bg-paper-deep px-3.5 text-[11.5px] font-semibold text-ink transition-colors duration-150 hover:bg-line-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-pin disabled:opacity-50"
            >
              {stopping ? "Stopping…" : "Stop"}
            </button>
          ) : (
            <Link
              href={refineHref}
              className="inline-flex min-h-11 flex-none items-center rounded-pill bg-paper-deep px-3.5 text-[11.5px] font-semibold text-ink no-underline transition-colors duration-150 hover:bg-line-soft"
            >
              Refine
            </Link>
          )}
        </MapBar>
      }
      mapOverlay={
        <>
          {inProgress ? (
            <>
              <MapActivityPing />
              <LiveStatusCard search={search} />
            </>
          ) : (
            status && <StatusPill tone={status.tone}>{status.text}</StatusPill>
          )}

          {stopError && (
            <div
              role="alert"
              className="absolute top-20 right-5 left-5 rounded-panel border border-pin/40 bg-surface-plain px-4 py-2.5 text-[12px] text-pin shadow-bar lg:left-auto lg:w-[330px]"
            >
              {stopError}
            </div>
          )}

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
