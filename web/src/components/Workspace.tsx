"use client";

import Image from "next/image";
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
import { logout } from "@/lib/auth";
import { CURATED_ROLES } from "@/lib/roles";
import { AddressInput, RadiusCircle, type LatLng } from "./map/MapPieces";
import RecentSearches from "./workspace/RecentSearches";
import { Button, Card, Pill } from "./ui";

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY!;
const SYDNEY = { lat: -33.8688, lng: 151.2093 };

function initials(me: Me): string {
  const source = me.name || me.email;
  return source
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="m-0 mb-2 text-[11px] font-bold tracking-[0.06em] text-slate-muted uppercase">
        {title}
      </h2>
      {children}
    </section>
  );
}

/**
 * Mockup 3 — the app's main shell. Left rail (history + who you are), centre map
 * (where), right panel (what + how far + go).
 *
 * Layout: three panes at >=1280px, two at >=768px with the rail dropping to a
 * full-width row, single column below that.
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

  // Radius choices come from GET /config — never hardcoded here. The literal is
  // only the pre-config placeholder; useMemo keeps it referentially stable so the
  // effect below doesn't re-run on every render.
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

  const maxRoles = config?.max_roles ?? 1;
  const unpicked = CURATED_ROLES.filter(
    (r) => !suggestions.some((s) => s.label === r),
  );

  return (
    <APIProvider apiKey={MAPS_KEY}>
      <div className="min-h-dvh px-4 py-4 sm:px-6 sm:py-6">
        <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-[264px_minmax(0,1fr)_360px]">
          {/* ── Left rail ─────────────────────────────────────────────── */}
          <Card className="order-3 grid h-fit content-start gap-6 p-5 md:order-none md:col-span-2 xl:col-span-1">
            <div className="flex items-center gap-2.5">
              <Image
                src="/logo.png"
                alt=""
                width={28}
                height={28}
                priority
                className="h-7 w-7 object-contain"
              />
              <span className="text-[13px] font-bold text-ink">
                Find Me a Job AI
              </span>
            </div>

            <Button variant="secondary" size="sm" onClick={onStartOver} block>
              New search
            </Button>

            <Section title="Recent searches">
              <RecentSearches searches={recent} loading={loadingRecent} />
            </Section>

            <Section title="Your profile">
              <div className="flex items-center gap-2.5">
                <span
                  aria-hidden="true"
                  className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-accent/10 text-[13px] font-semibold text-accent"
                >
                  {initials(me)}
                </span>
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-semibold text-ink">
                    {me.name || "You"}
                  </div>
                  <div className="truncate text-[12px] text-slate-muted">
                    {me.email}
                  </div>
                </div>
              </div>
              <p className="mt-3 mb-0 text-[12px] text-slate-muted">
                {me.free_search_used
                  ? "Free search used"
                  : "1 free search available"}
              </p>
              <Button
                variant="ghost"
                size="sm"
                className="mt-2 -ml-3"
                onClick={() => logout()}
              >
                Sign out
              </Button>
            </Section>
          </Card>

          {/* ── Centre: the map ───────────────────────────────────────── */}
          <Card className="order-1 grid content-start gap-3 p-5 md:order-none">
            <AddressInput onPlace={onPlace} />

            <div className="h-[320px] overflow-hidden rounded-panel border border-line xl:h-[520px]">
              <Map
                defaultZoom={13}
                center={center}
                mapId="fmaj-search"
                onClick={(e) => e.detail.latLng && setCenter(e.detail.latLng)}
                disableDefaultUI={false}
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
            </div>

            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-[13px] font-semibold text-ink">
                {locationLabel ||
                  `${center.lat.toFixed(4)}, ${center.lng.toFixed(4)}`}
              </span>
              <span className="text-[12px] text-slate-muted">
                Drag the pin to move the centre
              </span>
            </div>
          </Card>

          {/* ── Right: what to search for ─────────────────────────────── */}
          <Card className="order-2 grid h-fit content-start gap-6 p-5 md:order-none">
            <div>
              <h2 className="m-0 mb-1 text-lg font-extrabold text-ink">
                Ready when you are
              </h2>
              <p className="m-0 text-[13px] text-slate-muted">
                {suggestions.length === 1
                  ? "I found 1 role that matches what you told me"
                  : `I found ${suggestions.length} roles that match what you told me`}
              </p>
            </div>

            <Section title="Roles detected">
              <div className="flex flex-wrap gap-2">
                {suggestions.map((s) => {
                  const on = selected.includes(s.label);
                  return (
                    <Pill
                      key={s.label}
                      title={s.why}
                      selected={on}
                      onClick={() => onToggleRole(s.label)}
                    >
                      {on ? "✓ " : ""}
                      {s.label}
                    </Pill>
                  );
                })}
              </div>
              <p className="mt-2 mb-0 text-[12px] text-slate-muted">
                {maxRoles === 1
                  ? "One role per search on your current plan."
                  : `Up to ${maxRoles} roles per search.`}
              </p>

              {unpicked.length > 0 && (
                <details className="mt-3">
                  <summary className="cursor-pointer text-[12px] text-slate-muted">
                    Or pick a common role
                  </summary>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {unpicked.map((role) => (
                      <Pill key={role} dashed onClick={() => onAddRole(role)}>
                        + {role}
                      </Pill>
                    ))}
                  </div>
                </details>
              )}
            </Section>

            <Section title="Search radius">
              <div className="flex flex-wrap gap-2">
                {radiusOptions.map((km) => (
                  <Pill
                    key={km}
                    selected={radiusKm === km}
                    onClick={() => setRadiusKm(km)}
                  >
                    {km} km
                  </Pill>
                ))}
              </div>
            </Section>

            {error && (
              <p role="alert" className="m-0 text-[13px] text-pin">
                {error}
              </p>
            )}

            <Button
              size="lg"
              block
              onClick={start}
              disabled={submitting || selected.length === 0}
            >
              {submitting ? "Starting analysis…" : "Start analysis"}
            </Button>
          </Card>
        </div>
      </div>
    </APIProvider>
  );
}
