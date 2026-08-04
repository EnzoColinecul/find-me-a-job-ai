"use client";

import {
  createSearch,
  type AppConfig,
  type Me,
  type RoleSuggestion,
} from "@/lib/api";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AddressInput, type LatLng } from "./map/MapPieces";
import { MapBar } from "./workspace/MapBar";
import StartPanel from "./workspace/StartPanel";
import WorkspaceShell from "./workspace/WorkspaceShell";

const SYDNEY = { lat: -33.8688, lng: 151.2093 };

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
    <WorkspaceShell
      me={me}
      center={center}
      radiusKm={radiusKm}
      onCenterChange={setCenter}
      draggablePin
      onNewSearch={onStartOver}
      topBar={
        <MapBar>
          <AddressInput onPlace={onPlace} bias={center} />
          <span className="hidden flex-none text-[11.5px] text-slate-faint sm:block">
            Drag the pin to move the centre
          </span>
        </MapBar>
      }
      floatingPanel={panel}
      stackedPanel={panel}
    />
  );
}
