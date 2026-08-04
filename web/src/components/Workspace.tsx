"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { APIProvider, AdvancedMarker, Map } from "@vis.gl/react-google-maps";
import {
  createSearch,
  listSearches,
  type AppConfig,
  type Me,
  type RoleSuggestion,
  type SearchSummary,
} from "@/lib/api";
import { AddressInput, RadiusCircle, type LatLng } from "./map/MapPieces";
import Rail from "./workspace/Rail";
import StartPanel from "./workspace/StartPanel";

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY!;
const SYDNEY = { lat: -33.8688, lng: 151.2093 };

/**
 * Mockup 3 — the app's main shell. A fixed rail on the left, and the map filling
 * everything else with the search bar and the start panel floating over it.
 *
 * The map is the surface, not a widget inside a card: at >=1024px the panels are
 * absolutely positioned over it. Below that the rail and the panel become normal
 * blocks stacked under a shorter map, which is the mobile flow.
 */
export default function Workspace({
  me,
  config,
  suggestions,
  selected,
  onToggleRole,
  onAddRole,
  onStartOver,
}: {
  me: Me;
  config: AppConfig | null;
  suggestions: RoleSuggestion[];
  selected: string[];
  onToggleRole: (label: string) => void;
  onAddRole: (label: string) => void;
  onStartOver: () => void;
}) {
  const router = useRouter();
  const [center, setCenter] = useState<LatLng>(SYDNEY);
  const [locationLabel, setLocationLabel] = useState("");
  const [radiusKm, setRadiusKm] = useState<number>(5);
  const [recent, setRecent] = useState<SearchSummary[]>([]);
  const [loadingRecent, setLoadingRecent] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  useEffect(() => {
    listSearches()
      .then(setRecent)
      .catch(() => setRecent([]))
      .finally(() => setLoadingRecent(false));
  }, []);

  const onPlace = useCallback((p: LatLng, label: string) => {
    setCenter(p);
    setLocationLabel(label);
  }, []);

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
      onToggleRole={onToggleRole}
      onAddRole={onAddRole}
      onRadius={setRadiusKm}
      onStart={start}
    />
  );

  return (
    <APIProvider apiKey={MAPS_KEY}>
      <div className="flex min-h-dvh flex-col bg-surface-plain lg:h-dvh lg:flex-row lg:overflow-hidden">
        {/* ── Left rail ───────────────────────────────────────────────── */}
        <aside className="order-3 border-t border-rail-line bg-rail lg:order-none lg:w-[216px] lg:flex-none lg:border-t-0 lg:border-r lg:overflow-y-auto">
          <Rail
            me={me}
            recent={recent}
            loadingRecent={loadingRecent}
            onNewSearch={onStartOver}
          />
        </aside>

        {/* ── The map, and everything floating on it ──────────────────── */}
        <div className="relative order-1 h-[380px] flex-none overflow-hidden bg-paper-deep lg:order-none lg:h-auto lg:flex-1">
          <Map
            defaultZoom={13}
            center={center}
            mapId="fmaj-search"
            onClick={(e) => e.detail.latLng && setCenter(e.detail.latLng)}
            disableDefaultUI={false}
            className="h-full w-full"
          >
            <AdvancedMarker
              position={center}
              draggable
              onDragEnd={(e) =>
                e.latLng &&
                setCenter({ lat: e.latLng.lat(), lng: e.latLng.lng() })
              }
            />
            <RadiusCircle center={center} radiusKm={radiusKm} />
          </Map>

          {/* Floating address bar */}
          <div className="absolute top-4 right-4 left-4 flex items-center gap-2.5 rounded-panel border border-line-cool bg-surface-plain px-3.5 py-2.5 shadow-bar sm:top-4 sm:right-5 sm:left-5">
            <div className="min-w-0 flex-1">
              <AddressInput onPlace={onPlace} />
              {locationLabel && (
                <p className="m-0 truncate text-[12px] text-slate-muted">
                  {locationLabel}
                </p>
              )}
            </div>
            <span className="hidden flex-none text-[11.5px] text-slate-faint sm:block">
              Drag the pin to move the centre
            </span>
          </div>

          {/* The start panel floats over the map only when there's room for it */}
          <div className="absolute bottom-5 left-5 hidden w-[330px] rounded-float bg-surface-plain p-5 shadow-float lg:block">
            {panel}
          </div>
        </div>

        {/* Below lg the panel is a normal block rather than an overlay */}
        <div className="order-2 border-b border-rail-line bg-surface-plain px-5 py-5 lg:hidden">
          {panel}
        </div>
      </div>
    </APIProvider>
  );
}
