"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AddressInput, type LatLng } from "../map/MapPieces";
import { useReverseGeocode } from "../map/useReverseGeocode";
import { MapBar } from "./MapBar";

function LocateIcon({ busy }: { busy: boolean }) {
  if (busy) {
    return (
      <span className="block h-3.5 w-3.5 animate-[spin_0.8s_linear_infinite] rounded-full border-2 border-current/30 border-t-current" />
    );
  }
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
      <circle
        cx="12"
        cy="12"
        r="4"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path
        d="M12 2v3M12 19v3M2 12h3M19 12h3"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * The bar floating over the workspace map: address autocomplete, "Use my
 * location", and the reverse geocoding that keeps the field honest when the
 * centre is set by dragging the pin instead of typing.
 *
 * All three live here rather than in `Workspace` for one reason: geocoding and
 * autocomplete both need `useMapsLibrary`, which reads the loader off
 * `APIProvider` — and the provider is inside `WorkspaceShell`. `Workspace`
 * renders above it, so a hook called there would find no context.
 */
export default function MapSearchBar({
  center,
  label,
  resolve,
  autoLocate = false,
  onPick,
  onLabel,
  onLocated,
}: {
  center: LatLng;
  /** Current address for the field; "" while a moved pin is being resolved. */
  label: string;
  /** Point whose address needs looking up, or null when nothing is pending. */
  resolve: LatLng | null;
  /**
   * Fire geolocation once on mount, so a fresh workspace centres on the user
   * instead of a hardcoded default. Suppressed when the centre was prefilled
   * (e.g. arriving via "Refine") — nothing to auto-locate over.
   */
  autoLocate?: boolean;
  /** A place the user chose outright — coordinates and label together. */
  onPick: (p: LatLng, label: string) => void;
  /** The address for `resolve`, once it comes back. */
  onLabel: (label: string) => void;
  /** Geolocation succeeded — the caller moves focus on to the radius step. */
  onLocated: () => void;
}) {
  const reverseGeocode = useReverseGeocode();
  const [locating, setLocating] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  /*
   * Stamping, not cancellation: the Geocoder has no abort. Dragging the pin
   * twice in quick succession can land the first (stale) response last, so each
   * request records the point it was for and a result is only accepted if the
   * caller is still waiting on that same point.
   */
  const pendingRef = useRef<LatLng | null>(null);
  useEffect(() => {
    if (!resolve) return;
    pendingRef.current = resolve;
    let cancelled = false;
    void (async () => {
      const address = await reverseGeocode(resolve);
      if (cancelled || pendingRef.current !== resolve) return;
      onLabel(address);
    })();
    return () => {
      cancelled = true;
    };
  }, [resolve, reverseGeocode, onLabel]);

  const locate = useCallback(() => {
    setNote(null);

    // Secure-context only. On plain HTTP the API is either absent or silently
    // never calls back, so say so rather than spinning forever.
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setNote("Your browser can't share a location here. Search an address instead.");
      return;
    }

    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const p = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        // Cancel any in-flight pin lookup: this position supersedes it.
        pendingRef.current = null;
        const address = await reverseGeocode(p);
        setLocating(false);
        onPick(p, address);
        onLocated();
      },
      (err) => {
        setLocating(false);
        setNote(
          err.code === err.PERMISSION_DENIED
            ? "No problem — search an address instead."
            : "Couldn't get your location. Search an address instead.",
        );
      },
      // Coarse is fine: the pin stays draggable and the radius is kilometres.
      // A long timeout would leave the button spinning on a bad GPS fix.
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 },
    );
  }, [reverseGeocode, onPick, onLocated]);

  /*
   * Auto-locate on first mount — but only when the user has *already* granted
   * geolocation to this origin. An unprompted `getCurrentPosition` on a user who
   * isn't ready risks a sticky per-origin denial (and Chrome penalises unbidden
   * prompts), so we gate on the Permissions API and centre silently only on
   * "granted". "prompt"/"denied", no Permissions API, or an insecure context all
   * fall through to the manual "Use my location" button — no automatic prompt.
   * A ref guards against a prop change or StrictMode double-invoke re-firing it.
   */
  const autoLocatedRef = useRef(false);
  useEffect(() => {
    if (!autoLocate || autoLocatedRef.current) return;
    if (typeof navigator === "undefined" || !navigator.permissions?.query) return;
    autoLocatedRef.current = true;
    let cancelled = false;
    void navigator.permissions
      .query({ name: "geolocation" })
      .then((status) => {
        if (!cancelled && status.state === "granted") locate();
      })
      // Some browsers reject the "geolocation" name — treat as "don't auto-ask".
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [autoLocate, locate]);

  return (
    <div className="flex flex-col gap-1.5">
      <MapBar>
        <AddressInput onPlace={onPick} bias={center} value={label} />

        <button
          type="button"
          onClick={locate}
          disabled={locating}
          className="inline-flex min-h-11 flex-none items-center gap-1.5 rounded-pill border border-line-cool px-3 text-[12px] font-semibold text-ink transition-colors duration-150 hover:border-line-plain focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          <LocateIcon busy={locating} />
          <span className="hidden sm:inline">
            {locating ? "Finding you…" : "Use my location"}
          </span>
        </button>

        <span className="hidden flex-none text-[11.5px] text-slate-faint xl:block">
          Drag the pin to move the centre
        </span>
      </MapBar>

      {note && (
        // Deliberately not an alert dialog: a denied permission is a normal
        // answer, and the address flow underneath still works.
        <p
          aria-live="polite"
          className="m-0 self-start rounded-panel bg-surface-plain px-3 py-1.5 text-[12px] text-slate-muted shadow-bar"
        >
          {note}
        </p>
      )}
    </div>
  );
}
