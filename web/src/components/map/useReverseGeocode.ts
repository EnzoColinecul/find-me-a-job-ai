"use client";

import { useCallback, useEffect, useRef } from "react";
import type { RefObject } from "react";
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
 * Requires the **Geocoding API** enabled on the project and present in the
 * browser key's API restrictions — a different service from Maps JS and Places.
 * That was done on 2026-08-07 and is verified working from `localhost`; a
 * coordinate label today means the lookup raced the loader (below) or the
 * request genuinely failed, *not* that the key is unconfigured.
 */
const LIBRARY_WAIT_MS = 5_000;
const LIBRARY_POLL_MS = 100;

/**
 * Wait for the geocoding library, rather than giving up the instant it is
 * missing.
 *
 * `useMapsLibrary` returns null until Maps JS finishes loading, and the first
 * lookup of a session can easily beat it: auto-locate fires as soon as the
 * permission query resolves (~70ms), while the loader takes appreciably longer.
 * Bailing on null there labelled a perfectly good position with raw
 * coordinates purely because we asked early — and `POST /searches` then
 * persisted that string as `location_label`, which is why the recent-searches
 * rail is full of "Pinned location".
 *
 * Bounded, because the caller is holding a spinner: a key or network failure
 * must still fall through to the coordinate label instead of hanging.
 */
async function waitForLibrary(
  ref: RefObject<google.maps.GeocodingLibrary | null>,
): Promise<google.maps.GeocodingLibrary | null> {
  const deadline = Date.now() + LIBRARY_WAIT_MS;
  while (!ref.current && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, LIBRARY_POLL_MS));
  }
  return ref.current;
}

export function useReverseGeocode(): (p: LatLng) => Promise<string> {
  const geocoding = useMapsLibrary("geocoding");
  const geocoderRef = useRef<google.maps.Geocoder | null>(null);
  // Held in a ref so the returned callback can stay referentially stable — it
  // feeds `locate`'s dependencies in MapSearchBar — and so a lookup issued
  // before the loader finished can still pick the library up when it lands.
  const libraryRef = useRef<google.maps.GeocodingLibrary | null>(null);
  useEffect(() => {
    if (geocoding) libraryRef.current = geocoding;
  }, [geocoding]);

  return useCallback(async (p: LatLng): Promise<string> => {
    const library = libraryRef.current ?? (await waitForLibrary(libraryRef));
    if (!library) return formatLatLng(p);
    if (!geocoderRef.current) geocoderRef.current = new library.Geocoder();
    try {
      const { results } = await geocoderRef.current.geocode({ location: p });
      return results[0]?.formatted_address ?? formatLatLng(p);
    } catch {
      return formatLatLng(p);
    }
  }, []);
}
