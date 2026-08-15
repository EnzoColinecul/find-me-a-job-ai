"use client";

import { useCallback, useRef } from "react";
import { useMapsLibrary } from "@vis.gl/react-google-maps";
import type { LatLng } from "./MapPieces";

/** Last-resort label so a moved pin never leaves the bar blank. */
export function formatLatLng(p: LatLng): string {
  return `${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}`;
}

/**
 * Turns a point into a human-readable address.
 *
 * Must be called from inside `APIProvider` — `useMapsLibrary` reads the loader
 * off that context, so anything using this has to render within the shell's map
 * subtree rather than in `Workspace` itself.
 *
 * Never rejects: a failed lookup returns the coordinates. Losing the address is
 * a cosmetic problem, and the caller's job (moving the pin) has already
 * succeeded by the time we get here.
 *
 * ⚠️ **Needs the Geocoding API enabled** on the project *and* added to the
 * browser key's API restrictions — it is a different service from Maps JS and
 * Places, which is all `NEXT_PUBLIC_GOOGLE_MAPS_KEY` is currently allowed to
 * call. Until that's done every lookup silently falls back to coordinates,
 * which is the intended failure mode but is not the feature. `infra/gcp` only
 * manages the server-side Places key; the browser key is console-managed (see
 * CLAUDE.md), so this is a manual step there.
 */
export function useReverseGeocode(): (p: LatLng) => Promise<string> {
  const geocoding = useMapsLibrary("geocoding");
  const geocoderRef = useRef<google.maps.Geocoder | null>(null);

  return useCallback(
    async (p: LatLng): Promise<string> => {
      if (!geocoding) return formatLatLng(p);
      if (!geocoderRef.current) geocoderRef.current = new geocoding.Geocoder();
      try {
        const { results } = await geocoderRef.current.geocode({ location: p });
        return results[0]?.formatted_address ?? formatLatLng(p);
      } catch {
        return formatLatLng(p);
      }
    },
    [geocoding],
  );
}
