"use client";

import { useEffect, useRef, useState } from "react";
import {
  APIProvider,
  Map,
  AdvancedMarker,
  useMap,
  useMapsLibrary,
} from "@vis.gl/react-google-maps";
import { useRouter } from "next/navigation";
import {
  createSearch,
  getConfig,
  interpretRoles,
  type AppConfig,
  type RoleSuggestion,
} from "@/lib/api";
import { CURATED_ROLES } from "@/lib/roles";
import { Button, Card, Pill } from "@/components/ui";

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY!;
const SYDNEY = { lat: -33.8688, lng: 151.2093 };

/**
 * Google Maps' Circle takes literal colour strings, not CSS classes, so the
 * token has to be read off the document at runtime rather than hardcoded.
 */
function token(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return (
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() ||
    fallback
  );
}

type LatLng = { lat: number; lng: number };

/** Draws the radius circle around the selected point. */
function RadiusCircle({ center, radiusKm }: { center: LatLng; radiusKm: number }) {
  const map = useMap();
  const circleRef = useRef<google.maps.Circle | null>(null);

  useEffect(() => {
    if (!map) return;
    if (!circleRef.current) {
      const accent = token("--color-accent", "#3d6fb5");
      circleRef.current = new google.maps.Circle({
        map,
        strokeColor: accent,
        strokeWeight: 2,
        fillColor: accent,
        fillOpacity: 0.12,
      });
    }
    circleRef.current.setCenter(center);
    circleRef.current.setRadius(radiusKm * 1000);
    return () => {
      // keep circle alive across re-renders; removed on unmount below
    };
  }, [map, center, radiusKm]);

  useEffect(() => () => circleRef.current?.setMap(null), []);
  return null;
}

/** Address autocomplete using Places API (New) — PlaceAutocompleteElement. */
function AddressInput({ onPlace }: { onPlace: (p: LatLng) => void }) {
  const places = useMapsLibrary("places");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!places || !containerRef.current) return;
    // PlaceAutocompleteElement is a web component (Places API New).
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const el: any = new (places as any).PlaceAutocompleteElement({
      includedRegionCodes: ["au"],
    });
    el.style.width = "100%";
    containerRef.current.appendChild(el);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const onSelect = async (event: any) => {
      const place = event.placePrediction.toPlace();
      await place.fetchFields({ fields: ["location"] });
      const loc = place.location;
      if (loc) onPlace({ lat: loc.lat(), lng: loc.lng() });
    };
    el.addEventListener("gmp-select", onSelect);

    return () => {
      el.removeEventListener("gmp-select", onSelect);
      el.remove();
    };
  }, [places, onPlace]);

  return <div ref={containerRef} />;
}

export default function SearchForm() {
  const router = useRouter();
  const [center, setCenter] = useState<LatLng>(SYDNEY);
  const [radiusKm, setRadiusKm] = useState<number>(5);
  const [config, setConfig] = useState<AppConfig | null>(null);

  const [text, setText] = useState("");
  const [suggestions, setSuggestions] = useState<RoleSuggestion[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [interpreting, setInterpreting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    getConfig().then(setConfig).catch(() => setConfig(null));
  }, []);

  const maxRoles = config?.max_roles ?? 1;
  const radiusOptions = config?.radius_options_km ?? [1, 5, 10];

  const interpret = async () => {
    if (!text.trim()) return;
    setInterpreting(true);
    setError(null);
    try {
      const res = await interpretRoles(text);
      if (!res.ok || res.roles.length === 0) {
        // Don't fabricate a role out of their sentence — ask them to rephrase.
        setSuggestions(null);
        setSelected([]);
        setNotice(res.message || "Please try describing the work differently.");
        return;
      }
      setNotice(null);
      setSuggestions(res.roles);
      // preselect as many as the plan allows, in the LLM's priority order
      setSelected(res.roles.slice(0, res.max_roles).map((r) => r.label));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setInterpreting(false);
    }
  };

  const toggleSelected = (label: string) => {
    setSelected((prev) => {
      if (prev.includes(label)) return prev.filter((r) => r !== label);
      if (prev.length >= maxRoles) {
        // at the cap: replace the oldest so a single-role plan feels like "pick one"
        return maxRoles === 1 ? [label] : [...prev.slice(1), label];
      }
      return [...prev, label];
    });
  };

  const addCurated = (role: string) => {
    setSuggestions((prev) => {
      const list = prev ?? [];
      return list.some((r) => r.label === role)
        ? list
        : [...list, { label: role, curated_key: role, why: "You picked this one." }];
    });
    toggleSelected(role);
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const roles = selected.map((label) => {
        const s = suggestions?.find((r) => r.label === label);
        return { label, curated_key: s?.curated_key ?? null };
      });
      const id = await createSearch({
        lat: center.lat,
        lng: center.lng,
        radius_km: radiusKm,
        roles,
        query_text: text.trim() || undefined,
      });
      router.push(`/search/${id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  };

  return (
    <APIProvider apiKey={MAPS_KEY}>
      <div className="grid gap-3">
        <AddressInput onPlace={setCenter} />

        <div className="h-90 overflow-hidden rounded-panel border border-line">
          <Map
            defaultZoom={13}
            center={center}
            mapId="fmaj-search"
            onClick={(e) => e.detail.latLng && setCenter(e.detail.latLng)}
            disableDefaultUI={false}
          >
            <AdvancedMarker position={center} />
            <RadiusCircle center={center} radiusKm={radiusKm} />
          </Map>
        </div>

        <fieldset className="m-0 border-0 p-0">
          <legend className="mb-1.5 text-[13px] font-semibold text-ink">
            Search radius
          </legend>
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
        </fieldset>

        <div>
          <label
            htmlFor="what"
            className="mb-1.5 block text-[13px] font-semibold text-ink"
          >
            What kind of work are you looking for?
          </label>
          <textarea
            id="what"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. I'd like to work in a restaurant — I've done some kitchen work before"
            rows={3}
            className="w-full rounded-panel border border-line bg-surface-plain px-3.5 py-3 text-sm text-ink placeholder:text-slate-muted focus-visible:border-accent-strong focus-visible:outline-none"
          />
          <Button
            variant="secondary"
            size="sm"
            className="mt-2"
            onClick={interpret}
            disabled={interpreting || !text.trim()}
          >
            {interpreting ? "Thinking…" : suggestions ? "Re-interpret" : "Continue"}
          </Button>
        </div>

        {notice && (
          <Card role="status" className="border-warn/45 bg-warn/10 px-3.5 py-3">
            <span className="text-[13px] text-ink">⚠️ {notice}</span>
          </Card>
        )}

        {suggestions && (
          <div>
            <p className="m-0 mb-2 text-[13px] text-slate-muted">
              We&apos;ll search for{" "}
              <strong className="text-ink">
                {selected.join(", ") || "…pick one"}
              </strong>
              {maxRoles === 1
                ? " — choose one role for this search."
                : ` — up to ${maxRoles} roles.`}
            </p>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s) => {
                const on = selected.includes(s.label);
                return (
                  <Pill
                    key={s.label}
                    title={s.why}
                    selected={on}
                    onClick={() => toggleSelected(s.label)}
                  >
                    {on ? "✓ " : ""}
                    {s.label}
                  </Pill>
                );
              })}
            </div>
            <details className="mt-3">
              <summary className="cursor-pointer text-[13px] text-slate-muted">
                Or pick a common role
              </summary>
              <div className="mt-2 flex flex-wrap gap-2">
                {CURATED_ROLES.filter(
                  (r) => !suggestions.some((s) => s.label === r),
                ).map((role) => (
                  <Pill key={role} dashed onClick={() => addCurated(role)}>
                    + {role}
                  </Pill>
                ))}
              </div>
            </details>
          </div>
        )}

        {error && (
          <p role="alert" className="m-0 text-[13px] text-pin">
            {error}
          </p>
        )}

        <Button
          size="lg"
          block
          onClick={submit}
          disabled={submitting || selected.length === 0}
        >
          {submitting ? "Starting search…" : "Find jobs near here"}
        </Button>
      </div>
    </APIProvider>
  );
}
