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
import { createSearch } from "@/lib/api";
import { CURATED_ROLES, MAX_ROLES, RADIUS_OPTIONS_KM } from "@/lib/roles";

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
  const [roles, setRoles] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleRole = (role: string) => {
    setRoles((prev) =>
      prev.includes(role)
        ? prev.filter((r) => r !== role)
        : prev.length < MAX_ROLES
          ? [...prev, role]
          : prev,
    );
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const id = await createSearch({
        lat: center.lat,
        lng: center.lng,
        radius_km: radiusKm,
        roles,
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
            {RADIUS_OPTIONS_KM.map((km) => (
              <option key={km} value={km}>
                {km} km
              </option>
            ))}
          </select>
        </label>

        <div>
          <p style={{ margin: "0 0 0.4rem" }}>
            Roles (up to {MAX_ROLES}):{" "}
            <strong>{roles.join(", ") || "none selected"}</strong>
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
            {CURATED_ROLES.map((role) => (
              <button
                key={role}
                type="button"
                onClick={() => toggleRole(role)}
                style={{
                  padding: "0.35rem 0.7rem",
                  borderRadius: 999,
                  border: "1px solid #ccc",
                  background: roles.includes(role) ? "#2563eb" : "transparent",
                  color: roles.includes(role) ? "#fff" : "inherit",
                  cursor: "pointer",
                }}
              >
                {role}
              </button>
            ))}
          </div>
        </div>

        {error && <p style={{ color: "crimson", margin: 0 }}>{error}</p>}

        <button
          onClick={submit}
          disabled={submitting || roles.length === 0}
          style={{ padding: "0.7rem", fontSize: "1rem" }}
        >
          {submitting ? "Starting search…" : "Find jobs near here"}
        </button>
      </div>
    </APIProvider>
  );
}
