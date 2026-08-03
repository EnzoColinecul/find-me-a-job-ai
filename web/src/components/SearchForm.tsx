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

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY!;
const SYDNEY = { lat: -33.8688, lng: 151.2093 };

type LatLng = { lat: number; lng: number };

/** Draws the radius circle around the selected point. */
function RadiusCircle({ center, radiusKm }: { center: LatLng; radiusKm: number }) {
  const map = useMap();
  const circleRef = useRef<google.maps.Circle | null>(null);

  useEffect(() => {
    if (!map) return;
    if (!circleRef.current) {
      circleRef.current = new google.maps.Circle({
        map,
        strokeColor: "#2563eb",
        strokeWeight: 2,
        fillColor: "#2563eb",
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
      <div style={{ display: "grid", gap: "0.75rem" }}>
        <AddressInput onPlace={setCenter} />

        <div style={{ height: 360, borderRadius: 8, overflow: "hidden" }}>
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

        <label>
          Radius:{" "}
          <select
            value={radiusKm}
            onChange={(e) => setRadiusKm(Number(e.target.value))}
          >
            {radiusOptions.map((km) => (
              <option key={km} value={km}>
                {km} km
              </option>
            ))}
          </select>
        </label>

        <div>
          <label htmlFor="what" style={{ display: "block", marginBottom: "0.3rem" }}>
            What kind of work are you looking for?
          </label>
          <textarea
            id="what"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. I'd like to work in a restaurant — I've done some kitchen work before"
            rows={3}
            style={{ width: "100%", padding: "0.6rem", fontSize: "1rem",
                     fontFamily: "inherit" }}
          />
          <button
            type="button"
            onClick={interpret}
            disabled={interpreting || !text.trim()}
            style={{ marginTop: "0.4rem", padding: "0.5rem 0.9rem" }}
          >
            {interpreting ? "Thinking…" : suggestions ? "Re-interpret" : "Continue"}
          </button>
        </div>

        {suggestions && (
          <div>
            <p style={{ margin: "0 0 0.4rem" }}>
              We&apos;ll search for{" "}
              <strong>{selected.join(", ") || "…pick one"}</strong>
              {maxRoles === 1
                ? " — choose one role for this search."
                : ` — up to ${maxRoles} roles.`}
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
              {suggestions.map((s) => {
                const on = selected.includes(s.label);
                return (
                  <button
                    key={s.label}
                    type="button"
                    title={s.why}
                    onClick={() => toggleSelected(s.label)}
                    style={{
                      padding: "0.35rem 0.7rem",
                      borderRadius: 999,
                      border: `1px solid ${on ? "#2563eb" : "#ccc"}`,
                      background: on ? "#2563eb" : "transparent",
                      color: on ? "#fff" : "inherit",
                      cursor: "pointer",
                    }}
                  >
                    {on ? "✓ " : ""}
                    {s.label}
                  </button>
                );
              })}
            </div>
            <details style={{ marginTop: "0.6rem" }}>
              <summary style={{ cursor: "pointer", color: "#888" }}>
                Or pick a common role
              </summary>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem",
                            marginTop: "0.4rem" }}>
                {CURATED_ROLES.filter(
                  (r) => !suggestions.some((s) => s.label === r),
                ).map((role) => (
                  <button
                    key={role}
                    type="button"
                    onClick={() => addCurated(role)}
                    style={{
                      padding: "0.3rem 0.6rem", borderRadius: 999,
                      border: "1px dashed #999", background: "transparent",
                      color: "inherit", cursor: "pointer", fontSize: "0.9rem",
                    }}
                  >
                    + {role}
                  </button>
                ))}
              </div>
            </details>
          </div>
        )}

        {error && <p style={{ color: "crimson", margin: 0 }}>{error}</p>}

        <button
          onClick={submit}
          disabled={submitting || selected.length === 0}
          style={{ padding: "0.7rem", fontSize: "1rem" }}
        >
          {submitting ? "Starting search…" : "Find jobs near here"}
        </button>
      </div>
    </APIProvider>
  );
}
