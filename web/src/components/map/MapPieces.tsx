"use client";

import { useEffect, useRef } from "react";
import { useMap } from "@vis.gl/react-google-maps";

export type LatLng = { lat: number; lng: number };

export { default as AddressInput } from "./AddressInput";

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
