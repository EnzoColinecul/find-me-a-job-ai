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

/**
 * Draws the radius circle around the selected point.
 *
 * ⚠️ The lifecycle here is the whole point. The previous version created the
 * circle behind an `if (!circleRef.current)` guard and detached it in a
 * separate mount-only cleanup — which under React StrictMode (on in dev, see
 * `next.config.mjs`) meant: mount → create, unmount → `setMap(null)`, remount →
 * guard skips creation and nothing ever re-attaches it. **The circle was
 * invisible in dev, on every screen, always.** That is what made the map look
 * like it was ignoring the radius entirely.
 *
 * So: one effect owns creation *and* teardown for a given map, and a second
 * only pushes updates. A remount rebuilds the circle from the refs rather than
 * resurrecting a detached one.
 */
export function RadiusCircle({
  center,
  radiusKm,
}: {
  center: LatLng;
  radiusKm: number;
}) {
  const map = useMap();
  const circleRef = useRef<google.maps.Circle | null>(null);
  const { lat, lng } = center;

  // Latest values, for a circle created after a remount.
  const centerRef = useRef(center);
  const radiusRef = useRef(radiusKm);
  centerRef.current = center;
  radiusRef.current = radiusKm;

  useEffect(() => {
    if (!map) return;
    const accent = token("--color-accent", "#3d6fb5");
    const circle = new google.maps.Circle({
      map,
      strokeColor: accent,
      strokeWeight: 2,
      fillColor: accent,
      fillOpacity: 0.12,
      // The circle is scenery — it must never swallow a click meant for the
      // map (which is how you move the pin).
      clickable: false,
      center: centerRef.current,
      radius: radiusRef.current * 1000,
    });
    circleRef.current = circle;
    return () => {
      circle.setMap(null);
      if (circleRef.current === circle) circleRef.current = null;
    };
  }, [map]);

  useEffect(() => {
    circleRef.current?.setCenter({ lat, lng });
    circleRef.current?.setRadius(radiusKm * 1000);
  }, [lat, lng, radiusKm]);

  return null;
}

/**
 * Metres per pixel at zoom 0 on the equator, from the Web Mercator definition
 * (a 256 px world tile spanning 360°). Everything below is derived from it.
 */
const M_PER_PX_Z0 = 156543.03392;

/** How much of the shorter viewport edge the radius circle should take up. */
const FIT_RATIO = 0.78;

/** The margin that leaves, as a share of that edge, per side. */
const PAD_RATIO = (1 - FIT_RATIO) / 2;

/** The map's true scale at a given camera. */
export function metresPerPixelAtZoom(lat: number, zoom: number): number {
  return (M_PER_PX_Z0 * Math.cos((lat * Math.PI) / 180)) / 2 ** zoom;
}

/**
 * A rough zoom for a first frame, before the map element has been measured.
 *
 * Only good enough for `defaultZoom`: `FitToRadius` re-frames properly as soon
 * as the map exists. Don't reach for this to reason about the map's real
 * scale — ask the camera (`metresPerPixelAtZoom`), because Google may snap the
 * zoom it was given.
 */
export function zoomForRadius(
  radiusKm: number,
  viewportPx: number,
  lat: number,
): number {
  const mPerPx =
    (Math.max(radiusKm, 0.05) * 2000) / (Math.max(viewportPx, 1) * FIT_RATIO);
  const z = Math.log2(metresPerPixelAtZoom(lat, 0) / mPerPx);
  return Math.min(20, Math.max(3, Math.floor(z)));
}

/**
 * Frames the camera on the radius circle instead of a fixed zoom.
 *
 * The map used to be hardcoded to `defaultZoom={13}`, which is metro scale: a
 * 1 km search rendered its circle a few pixels wide and dropped every pin into
 * one unreadable clump. Framing the search is what turns the map from
 * decoration into the feature.
 *
 * `fitBounds` rather than `setZoom`, deliberately. Computing the zoom
 * ourselves looks tidier and is subtly wrong: this map snaps the value it is
 * given to a whole zoom level, so a computed 15.6 becomes 16 and crops the
 * circle we were trying to fit. `fitBounds` is told the rectangle that must be
 * visible and is allowed to pick the camera that shows it.
 *
 * Deliberately *not* driven by the `<Map zoom>` prop: that prop is controlled
 * (the library re-applies it on every render), so setting it would take zooming
 * away from the user. This frames once per radius change, then leaves the
 * camera alone.
 *
 * The latitude dep is rounded to a whole degree on purpose — it barely moves
 * the answer, and depending on the raw value would re-frame every time the user
 * nudges the pin, throwing away whatever zoom they had chosen.
 */
export function FitToRadius({
  center,
  radiusKm,
}: {
  center: LatLng;
  radiusKm: number;
}) {
  const map = useMap();
  const centerRef = useRef(center);
  centerRef.current = center;

  useEffect(() => {
    if (!map) return;
    const div = map.getDiv();

    const fit = () => {
      const { width, height } = div.getBoundingClientRect();
      if (!width || !height) return false;
      const bounds = new google.maps.Circle({
        center: centerRef.current,
        radius: Math.max(radiusKm, 0.05) * 1000,
      }).getBounds();
      if (!bounds) return false;
      map.fitBounds(bounds, Math.round(Math.min(width, height) * PAD_RATIO));
      return true;
    };

    // On the first paint the map element can still be 0x0 (it mounts before
    // the flex layout settles), so fall back to a resize observer rather than
    // silently keeping the wrong camera.
    if (fit()) return;
    const ro = new ResizeObserver(() => {
      if (fit()) ro.disconnect();
    });
    ro.observe(div);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, radiusKm, Math.round(center.lat)]);

  return null;
}
