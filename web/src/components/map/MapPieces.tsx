"use client";

import { useEffect, useRef } from "react";
import { useMap, useMapsLibrary } from "@vis.gl/react-google-maps";

export type LatLng = { lat: number; lng: number };

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

/** Draws the radius circle around the selected point. */
export function RadiusCircle({
  center,
  radiusKm,
}: {
  center: LatLng;
  radiusKm: number;
}) {
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
  }, [map, center, radiusKm]);

  useEffect(() => () => circleRef.current?.setMap(null), []);
  return null;
}

/**
 * Address autocomplete using Places API (New) — PlaceAutocompleteElement.
 * Reports both the coordinates and the human-readable label, which the search
 * stores so the workspace's recent-searches rail can say "Surry Hills" rather
 * than a pair of decimals.
 */
export function AddressInput({
  onPlace,
}: {
  onPlace: (p: LatLng, label: string) => void;
}) {
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
      await place.fetchFields({ fields: ["location", "formattedAddress"] });
      const loc = place.location;
      if (loc) {
        onPlace(
          { lat: loc.lat(), lng: loc.lng() },
          place.formattedAddress ?? "",
        );
      }
    };
    el.addEventListener("gmp-select", onSelect);

    return () => {
      el.removeEventListener("gmp-select", onSelect);
      el.remove();
    };
  }, [places, onPlace]);

  return <div ref={containerRef} />;
}
