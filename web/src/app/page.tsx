"use client";

import { useEffect, useState } from "react";
import {
  getConfig,
  getMe,
  interpretRoles,
  listSearches,
  type AppConfig,
  type Me,
  type RoleSuggestion,
  type SearchSummary,
} from "@/lib/api";
import LoginScreen from "@/components/LoginScreen";
import HomeScreen from "@/components/HomeScreen";
import AskOverlay from "@/components/AskOverlay";
import Workspace from "@/components/Workspace";
import { CURATED_ROLES } from "@/lib/roles";

/** Parameters carried over from a "Refine" link, so the workspace opens prefilled. */
type RefinePrefill = {
  center: { lat: number; lng: number };
  radiusKm?: number;
  locationLabel: string;
};

/** Shown wherever the free search is spent. One wording, three places. */
const QUOTA_SPENT =
  "You've used your free search. Your past results are still here in the rail.";

/**
 * The front door.
 *
 *   signed out                → login (map hero)
 *   signed in, first ever     → home (full-screen conversational opening)
 *   signed in, been here      → workspace, with the same question overlaid
 *   roles interpreted         → workspace
 *
 * The workspace is mounted once and stays mounted: the overlay renders on top
 * of it rather than instead of it, so dismissing and reopening the question
 * doesn't reset the map centre, the radius, or a half-finished pin drag.
 */
export default function Home() {
  const [me, setMe] = useState<Me | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [recent, setRecent] = useState<SearchSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const [suggestions, setSuggestions] = useState<RoleSuggestion[] | null>(null);
  const [asking, setAsking] = useState(true);
  /**
   * Sticky: `GET /searches` is fetched once on load, so a user who arrives with
   * no history and interprets a role has a workspace the list doesn't know
   * about. Without this, "New search" would drop them back to the full-screen
   * greeting mid-session — the exact regression the overlay exists to fix.
   */
  const [hasWorkspace, setHasWorkspace] = useState(false);
  const [interpreting, setInterpreting] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  /** Set once on load when the user arrived via a "Refine" link. */
  const [refine, setRefine] = useState<RefinePrefill | null>(null);

  useEffect(() => {
    let done = false;
    void (async () => {
      const who = await getMe().catch(() => null);
      if (done) return;
      setMe(who);
      // Recent searches decide first-visit vs returning, so `/` needs them
      // before its first paint and passes them down rather than letting the
      // shell fetch the same list a second time.
      if (who) {
        const [list] = await Promise.all([
          listSearches().catch(() => [] as SearchSummary[]),
          getConfig()
            .then(setConfig)
            .catch(() => setConfig(null)),
        ]);
        if (done) return;
        setRecent(list);
        setHasWorkspace(list.length > 0);
        // Spent accounts open on their workspace, not on a question they're not
        // allowed to answer.
        setAsking(!who.free_search_used);

        // Arrived from "Refine": prefill the workspace from the query string
        // rather than asking the roles question again. Read from the URL in the
        // effect (not useSearchParams) to keep this client-only — no Suspense
        // boundary, no hydration mismatch.
        const sp = new URLSearchParams(window.location.search);
        const roleLabels = sp.getAll("role").filter(Boolean);
        const lat = Number(sp.get("lat"));
        const lng = Number(sp.get("lng"));
        if (roleLabels.length > 0 && Number.isFinite(lat) && Number.isFinite(lng)) {
          const radius = Number(sp.get("radius"));
          // The stored search only kept role labels, so re-derive a curated key
          // when the label is itself a curated role and leave it null otherwise
          // — the backend falls back to label-based venue types either way.
          const curated = new Set<string>(CURATED_ROLES);
          setSuggestions(
            roleLabels.map((label) => ({
              label,
              curated_key: curated.has(label) ? label : null,
              why: "Carried over from your last search.",
            })),
          );
          setSelected(roleLabels);
          setAsking(false);
          setHasWorkspace(true);
          setRefine({
            center: { lat, lng },
            radiusKm: Number.isFinite(radius) && radius > 0 ? radius : undefined,
            locationLabel: sp.get("loc") ?? "",
          });
        }
      }
      setLoading(false);
    })();
    return () => {
      done = true;
    };
  }, []);

  const maxRoles = config?.max_roles ?? 1;
  const quotaSpent = Boolean(me?.free_search_used);

  const interpret = async (text: string) => {
    // Belt and braces: the input and both entry points are already disabled
    // when the quota is gone, and this is the last thing between a stray call
    // site and a billed LLM request.
    if (quotaSpent) return;
    setInterpreting(true);
    setError(null);
    try {
      const res = await interpretRoles(text);
      if (!res.ok || res.roles.length === 0) {
        // Don't fabricate a role out of their sentence — ask them to rephrase.
        setError(res.message || "Please try describing the work differently.");
        return;
      }
      setSuggestions(res.roles);
      setSelected(res.roles.slice(0, res.max_roles).map((r) => r.label));
      setAsking(false);
      setHasWorkspace(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setInterpreting(false);
    }
  };

  const toggleRole = (label: string) => {
    setSelected((prev) => {
      if (prev.includes(label)) return prev.filter((r) => r !== label);
      if (prev.length >= maxRoles) {
        // At the cap: replace the oldest, so a single-role plan feels like
        // "pick one" rather than a silently ignored tap.
        return maxRoles === 1 ? [label] : [...prev.slice(1), label];
      }
      return [...prev, label];
    });
  };

  const addRole = (label: string) => {
    setSuggestions((prev) => {
      const list = prev ?? [];
      return list.some((r) => r.label === label)
        ? list
        : [...list, { label, curated_key: label, why: "You picked this one." }];
    });
    toggleRole(label);
  };

  const startOver = () => {
    setSuggestions(null);
    setSelected([]);
    setError(null);
    setAsking(true);
  };

  if (loading) {
    return (
      <main className="flex min-h-dvh items-center justify-center px-4">
        <p className="text-sm text-slate-muted">Loading…</p>
      </main>
    );
  }

  if (!me) return <LoginScreen />;

  // Nothing behind the overlay to dismiss to, so the greeting keeps the whole
  // screen. "Click outside to go back" needs a back to go to.
  const firstVisit = recent.length === 0 && !hasWorkspace;
  if (firstVisit) {
    return (
      <HomeScreen
        me={me}
        busy={interpreting}
        error={error}
        blockedReason={quotaSpent ? QUOTA_SPENT : null}
        onSubmit={interpret}
      />
    );
  }

  return (
    <>
      <Workspace
        me={me}
        config={config}
        suggestions={suggestions ?? []}
        selected={selected}
        initialCenter={refine?.center}
        initialRadiusKm={refine?.radiusKm}
        initialLocationLabel={refine?.locationLabel}
        recent={recent}
        loadingRecent={false}
        onToggleRole={toggleRole}
        onAddRole={addRole}
        onStartOver={startOver}
        newSearchDisabledReason={quotaSpent ? QUOTA_SPENT : null}
      />
      {asking && (
        <AskOverlay
          me={me}
          busy={interpreting}
          error={error}
          blockedReason={quotaSpent ? QUOTA_SPENT : null}
          onSubmit={interpret}
          onDismiss={() => setAsking(false)}
        />
      )}
    </>
  );
}
