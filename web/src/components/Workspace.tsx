"use client";

import {
  createSearch,
  type AppConfig,
  type Me,
  type RoleSuggestion,
  type SearchSummary,
} from "@/lib/api";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { type LatLng } from "./map/MapPieces";
import MapSearchBar from "./workspace/MapSearchBar";
import StartPanel from "./workspace/StartPanel";
import WorkspaceShell from "./workspace/WorkspaceShell";

// Not the default centre any more — a fallback. A fresh workspace auto-requests
// the user's location on mount (see `autoLocate` below); this is only what the
// map shows while that resolves, or if the user denies or can't share one.
const SYDNEY_FALLBACK = { lat: -33.8688, lng: 151.2093 };

/**
 * Mockup 3 — choose the place, confirm the roles, spend the search.
 *
 * The layout lives in WorkspaceShell, shared with the results screen; this
 * component owns the search parameters and the one button that submits them.
 */
export default function Workspace({
  me,
  config,
  suggestions,
  selected,
  initialCenter,
  initialRadiusKm,
  initialLocationLabel,
  recent,
  loadingRecent,
  onToggleRole,
  onAddRole,
  onStartOver,
  newSearchDisabledReason,
}: {
  me: Me;
  config: AppConfig | null;
  suggestions: RoleSuggestion[];
  selected: string[];
  /** When the user arrived via "Refine", the previous search's parameters. */
  initialCenter?: LatLng;
  initialRadiusKm?: number;
  initialLocationLabel?: string;
  /** Passed down so `page.tsx` and the shell share one `GET /searches`. */
  recent?: SearchSummary[];
  loadingRecent?: boolean;
  onToggleRole: (label: string) => void;
  onAddRole: (label: string) => void;
  onStartOver: () => void;
  newSearchDisabledReason?: string | null;
}) {
  const router = useRouter();
  const [center, setCenter] = useState<LatLng>(initialCenter ?? SYDNEY_FALLBACK);
  const [locationLabel, setLocationLabel] = useState(initialLocationLabel ?? "");
  /** Pin position waiting on an address. Null while nothing is outstanding. */
  const [resolving, setResolving] = useState<LatLng | null>(null);
  const [radiusKm, setRadiusKm] = useState<number>(initialRadiusKm ?? 5);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Bumped when geolocation lands, to move focus on to the radius choices. */
  const [focusRadius, setFocusRadius] = useState(0);

  // Radius choices come from GET /config — never hardcoded. The literal is only
  // the pre-config placeholder; useMemo keeps it referentially stable so the
  // effect below doesn't re-run every render.
  const radiusOptions = useMemo(
    () => config?.radius_options_km ?? [1, 5, 10],
    [config],
  );

  useEffect(() => {
    if (!radiusOptions.includes(radiusKm)) setRadiusKm(radiusOptions[0]);
  }, [radiusOptions, radiusKm]);

  /** Autocomplete or geolocation: coordinates and address arrive together. */
  const onPick = useCallback((p: LatLng, label: string) => {
    setCenter(p);
    setLocationLabel(label);
    setResolving(null);
  }, []);

  /*
   * Pin dragged, or the map clicked. The old address now describes somewhere
   * else, so clear it immediately and ask the bar to look up the new point —
   * showing a stale suburb next to a moved pin is worse than showing nothing.
   *
   * `onDragEnd`/`onClick` are the only callers, so this is once per settled
   * position, not once per drag frame.
   */
  const onPinMove = useCallback((p: LatLng) => {
    setCenter(p);
    setLocationLabel("");
    setResolving(p);
  }, []);

  const onLabel = useCallback((label: string) => {
    setLocationLabel(label);
    setResolving(null);
  }, []);

  const onLocated = useCallback(() => setFocusRadius((n) => n + 1), []);

  const start = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const roles = selected.map((label) => {
        const s = suggestions.find((r) => r.label === label);
        return { label, curated_key: s?.curated_key ?? null };
      });
      const id = await createSearch({
        lat: center.lat,
        lng: center.lng,
        radius_km: radiusKm,
        roles,
        location_label: locationLabel || undefined,
      });
      router.push(`/search/${id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  };

  const panel = (
    <StartPanel
      config={config}
      suggestions={suggestions}
      selected={selected}
      radiusKm={radiusKm}
      radiusOptions={radiusOptions}
      submitting={submitting}
      error={error}
      focusRadiusSignal={focusRadius}
      onToggleRole={onToggleRole}
      onAddRole={onAddRole}
      onRadius={setRadiusKm}
      onStart={start}
    />
  );

  return (
    <WorkspaceShell
      me={me}
      center={center}
      radiusKm={radiusKm}
      onCenterChange={onPinMove}
      draggablePin
      recent={recent}
      loadingRecent={loadingRecent}
      onNewSearch={onStartOver}
      newSearchDisabledReason={newSearchDisabledReason}
      topBar={
        <MapSearchBar
          center={center}
          label={locationLabel}
          resolve={resolving}
          autoLocate={!initialCenter}
          onPick={onPick}
          onLabel={onLabel}
          onLocated={onLocated}
        />
      }
      floatingPanel={panel}
      stackedPanel={panel}
    />
  );
}
