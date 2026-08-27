"use client";

import { listSearches, type Me, type SearchSummary } from "@/lib/api";
import { APIProvider, AdvancedMarker, Map } from "@vis.gl/react-google-maps";
import { PanelRightClose, PanelRightOpen } from "lucide-react";
import { useEffect, useState } from "react";
import {
  FitToRadius,
  metresPerPixelAtZoom,
  RadiusCircle,
  zoomForRadius,
  type LatLng,
} from "../map/MapPieces";
import { fanOutPins } from "@/lib/pins";
import Rail from "./Rail";

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY!;

/**
 * A stand-in map size for the very first frame, before the real element has
 * been measured. `FitToRadius` re-frames as soon as the map exists, and the
 * camera then reports its own scale, so this only has to be plausible.
 */
const NOMINAL_MAP_PX = 600;
const DEFAULT_FIRST_ZOOM = 13;

/**
 * The numbered badge dropped on the map for each result. All pins use
 * `--accent-strong` (blue), matching the card numbers. Hovering a card enlarges
 * its pin and rings it so the eye can find it.
 */
function NumberedPin({
  index,
  highlighted,
  offset,
}: {
  index: number;
  highlighted: boolean;
  /** CSS px nudge that separates this pin from others at the same spot. */
  offset?: { x: number; y: number };
}) {
  const nudged = Boolean(offset && (offset.x !== 0 || offset.y !== 0));
  return (
    <span
      className="relative block"
      style={
        nudged
          ? { transform: `translate(${offset!.x}px, ${offset!.y}px)` }
          : undefined
      }
    >
      {/* A fanned pin no longer sits on its own coordinate, so draw a stub back
          to it — otherwise the map is quietly lying about where the venue is. */}
      {nudged && (
        <span
          aria-hidden="true"
          className="absolute top-1/2 left-1/2 block h-px origin-left bg-accent-strong/60"
          style={{
            width: `${Math.hypot(offset!.x, offset!.y)}px`,
            transform: `rotate(${Math.atan2(-offset!.y, -offset!.x)}rad)`,
          }}
        />
      )}
      <span
        className={[
          "flex items-center justify-center rounded-full text-[12px] font-bold text-white",
          "border-2 border-white shadow-pin transition-transform duration-150",
          "bg-accent-strong",
          highlighted ? "h-8 w-8 scale-110 ring-2 ring-accent-strong" : "h-6 w-6",
        ].join(" ")}
      >
        {index}
      </span>
    </span>
  );
}

/**
 * The chrome shared by mockups 3 and 4: rail on the left, map filling the
 * middle, an optional results panel on the right.
 *
 * Both `/` and `/search/[id]` render this — mockup 4 is the same shell as
 * mockup 3 with the right panel open, which is why the results moved off their
 * own standalone page.
 */
export default function WorkspaceShell({
  me,
  center,
  radiusKm,
  onCenterChange,
  draggablePin = false,
  markers,
  highlightedMarkerId,
  topBar,
  mapOverlay,
  floatingPanel,
  stackedPanel,
  rightPanel,
  rightPanelTitle,
  rightPanelSwitch,
  recent: recentProp,
  loadingRecent: loadingRecentProp,
  onNewSearch,
  newSearchDisabledReason,
}: {
  me: Me;
  center: LatLng;
  radiusKm: number;
  onCenterChange?: (p: LatLng) => void;
  /** Only the workspace lets you move the pin; results are a fixed record. */
  draggablePin?: boolean;
  /**
   * Numbered result pins (mockup 4). Numbers must match the result cards, so the
   * caller derives both from the same ordered list. Empty/undefined → no pins.
   */
  markers?: Array<{
    id: string;
    position: LatLng;
    index: number;
    featured: boolean;
  }>;
  /** The pin whose card is currently hovered/focused, enlarged to match. */
  highlightedMarkerId?: string | null;
  /** Floats at the top of the map — address input, or the search summary. */
  topBar: React.ReactNode;
  /** Anything else over the map, e.g. the results status pill. */
  mapOverlay?: React.ReactNode;
  /** Panel floating bottom-left over the map at >=lg (the workspace's). */
  floatingPanel?: React.ReactNode;
  /** The same panel rendered as a normal block below lg. */
  stackedPanel?: React.ReactNode;
  /** Results column. When null the column is not rendered at all. */
  rightPanel?: React.ReactNode;
  rightPanelTitle?: string;
  /** Optional control in the column header, e.g. switching trace ⇄ results. */
  rightPanelSwitch?: React.ReactNode;
  /**
   * Recent searches, when the caller already has them. `/` needs the list
   * before it renders (to decide first visit vs returning) so it fetches and
   * passes them down; `/search/[id]` doesn't, and lets the shell fetch.
   */
  recent?: SearchSummary[];
  loadingRecent?: boolean;
  onNewSearch: () => void;
  /** When set, "New search" is disabled and this explains why. */
  newSearchDisabledReason?: string | null;
}) {
  const provided = recentProp !== undefined;
  const [ownRecent, setOwnRecent] = useState<SearchSummary[]>([]);
  const [ownLoading, setOwnLoading] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  /**
   * The Maps SDK takes ~3s to boot; until it paints, the map area is blank
   * white. Cover it with paper + a shimmer so the page doesn't look broken.
   *
   * Cleared by `idle` **or** `tilesloaded`, whichever lands first, plus a hard
   * timeout below. `tilesloaded` alone is not enough: on a vector map it did
   * not fire on first paint here, and the shimmer sat over a perfectly good map
   * until a click forced a redraw. A loading state that can outlive the loading
   * is worse than no loading state at all.
   */
  const [tilesReady, setTilesReady] = useState(false);

  useEffect(() => {
    if (tilesReady) return;
    const t = setTimeout(() => setTilesReady(true), 4000);
    return () => clearTimeout(t);
  }, [tilesReady]);

  /**
   * The map's real ground scale, read off the camera.
   *
   * This is what says how far apart two result pins have to be *on the ground*
   * before they stop overlapping *on screen* — and the honest answer changes
   * with the viewport (a 380px-tall phone map is roughly 1.6x tighter than a
   * desktop column) and with wherever the user has zoomed to since. Two earlier
   * versions guessed it instead: one assumed a nominal 600px map, the other
   * assumed the zoom `FitToRadius` asked for, which this map rounds. Asking the
   * camera is the only version that can't be wrong.
   */
  const [mPerPx, setMPerPx] = useState(() =>
    metresPerPixelAtZoom(center.lat, DEFAULT_FIRST_ZOOM),
  );

  useEffect(() => {
    if (provided) return;
    listSearches()
      .then(setOwnRecent)
      .catch(() => setOwnRecent([]))
      .finally(() => setOwnLoading(false));
  }, [provided]);

  const recent = recentProp ?? ownRecent;
  const loadingRecent = provided ? (loadingRecentProp ?? false) : ownLoading;

  // Nothing to show → no column, no toggle, no empty gutter.
  const hasRight = Boolean(rightPanel);

  // Cheap for the couple of dozen markers this ever sees, so it just runs.
  const fannedMarkers = fanOutPins(
    (markers ?? []).map((m) => ({ ...m, ...m.position })),
    mPerPx,
  );

  return (
    <APIProvider apiKey={MAPS_KEY}>
      {/*
        * At >=lg this is an app frame, not a document: `fixed inset-0` takes it
        * out of flow entirely so nothing can give the page a few stray pixels
        * of scroll (which used to slide the rail and the map bar up). Below lg
        * it is an ordinary stacked page again.
        */}
      <div className="flex min-h-dvh flex-col bg-surface-plain lg:fixed lg:inset-0 lg:min-h-0 lg:flex-row lg:overflow-hidden">
        {/*
          * The rail carries the primary action ("New search"), the history and
          * the account block, so on a phone it leads — it used to sit after
          * every result card, a ~4000px scroll from the thing you came to do.
          * Below lg `Rail` collapses itself to a one-line header.
          */}
        {/*
          * `overflow-hidden`, not `overflow-y-auto`: at >=lg the rail is a
          * fixed frame and only the recent-searches list inside it scrolls, so
          * the mark, "New search" and the account block stay put. Putting the
          * scroll here instead moves all of them.
          */}
        <aside className="order-1 border-b border-rail-line bg-rail lg:order-none lg:w-[216px] lg:flex-none lg:overflow-hidden lg:border-b-0 lg:border-r">
          <Rail
            me={me}
            recent={recent}
            loadingRecent={loadingRecent}
            onNewSearch={onNewSearch}
            newSearchDisabledReason={newSearchDisabledReason}
          />
        </aside>

        {/* ── The map, and everything floating on it ──────────────────── */}
        <div
          className="relative order-2 h-[380px] flex-none overflow-hidden bg-paper-deep lg:order-none lg:h-auto lg:flex-1"
        >
          <Map
            /* A first-frame guess from a nominal viewport; `FitToRadius` below
               corrects it as soon as the map element has been measured. The
               camera must follow the search radius — a fixed zoom rendered a
               1 km search at metro scale. */
            defaultZoom={zoomForRadius(radiusKm, NOMINAL_MAP_PX, center.lat)}
            center={center}
            mapId="fmaj-search"
            className="h-full w-full"
            onClick={(e) =>
              e.detail.latLng && onCenterChange?.(e.detail.latLng)
            }
            /*
             * The map should read as our surface, not as an embedded Google
             * widget: no zoom buttons, no Street View pegman, no camera puck,
             * no map-type or fullscreen chrome.
             *
             * `keyboardShortcuts` stays ON deliberately — it is the only way to
             * pan and zoom without a mouse once the buttons are gone, and
             * turning it off would make the map keyboard-inoperable.
             *
             * The Google wordmark and the "Terms"/"Report a map error" links
             * cannot be removed: the Maps ToS requires them to stay visible and
             * unobscured. See the note in CLAUDE.md.
             */
            disableDefaultUI
            zoomControl={false}
            cameraControl={false}
            streetViewControl={false}
            mapTypeControl={false}
            fullscreenControl={false}
            scaleControl={false}
            rotateControl={false}
            clickableIcons={false}
            gestureHandling="greedy"
            onTilesLoaded={() => setTilesReady(true)}
            onIdle={() => setTilesReady(true)}
            onCameraChanged={(e) => {
              // Fires on every camera move, so only take a change worth
              // re-laying-out the pins for.
              const next = metresPerPixelAtZoom(
                e.detail.center.lat,
                e.detail.zoom,
              );
              setMPerPx((prev) =>
                Math.abs(prev - next) / next > 0.02 ? next : prev,
              );
            }}
          >
            <AdvancedMarker
              position={center}
              draggable={draggablePin}
              onDragEnd={(e) =>
                e.latLng &&
                onCenterChange?.({ lat: e.latLng.lat(), lng: e.latLng.lng() })
              }
            />
            <RadiusCircle center={center} radiusKm={radiusKm} />
            <FitToRadius center={center} radiusKm={radiusKm} />

            {/* Numbered result pins (mockup 4). zIndex lifts the highlighted one
                and the featured #1 above the rest so they can't be hidden. */}
            {fannedMarkers.map(({ item: m, offset }) => (
              <AdvancedMarker
                key={m.id}
                position={m.position}
                zIndex={
                  highlightedMarkerId === m.id ? 30 : m.featured ? 20 : 10
                }
              >
                <NumberedPin
                  index={m.index}
                  highlighted={highlightedMarkerId === m.id}
                  offset={offset}
                />
              </AdvancedMarker>
            ))}
          </Map>

          {!tilesReady && (
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 bg-paper-deep"
            >
              <div className="h-full w-full animate-[mapShimmer_1.6s_ease-in-out_infinite] bg-[linear-gradient(100deg,transparent_20%,var(--color-surface)_50%,transparent_80%)] opacity-70" />
            </div>
          )}

          {/* On lg the sidebar toggle floats at the map's top-right corner, so
              pull the search bar's right edge in to leave it clear room. */}
          <div className="absolute top-2 right-4 left-4 sm:right-5 sm:left-5 lg:right-16">
            {topBar}
          </div>

          {mapOverlay}

          {floatingPanel && (
            <div className="absolute bottom-5 left-5 hidden w-[330px] rounded-float bg-surface-plain p-5 shadow-float lg:block">
              {floatingPanel}
            </div>
          )}
        </div>

        {stackedPanel && (
          <div className="order-3 border-b border-rail-line bg-surface-plain px-5 py-5 lg:hidden">
            {stackedPanel}
          </div>
        )}

        {/* ── Results column ──────────────────────────────────────────── */}
        {hasRight && (
          <section
            aria-label={rightPanelTitle ?? "Results"}
            className={[
              // Mobile: a normal stacked block with the panel surface.
              "order-3 flex flex-col border-t border-rail-line bg-surface-plain",
              "lg:relative lg:order-none lg:border-t-0",
              // Desktop open: a 330px surface with a left divider.
              // Desktop collapsed: width + surface fully gone, so only the
              // floating toggle (positioned against this column's right edge)
              // is left over the map — no empty white strip.
              rightOpen
                ? "lg:w-[330px] lg:border-l lg:bg-surface-plain"
                : "lg:w-0 lg:border-l-0 lg:bg-transparent",
              "lg:flex-none lg:transition-[width] lg:duration-200",
            ].join(" ")}
          >
            {/*
             * The collapse-to-a-strip button is a >=lg affordance: below that
             * the panel is just the next block in the page, and hiding it
             * behind a 44px strip would only hide the content the user came
             * for. The trace<->results switch is not that — a phone user who
             * lands on results still needs a way back to "what I did", so the
             * row itself (and the switch inside it) stays visible at every
             * width; only the collapse button is lg-only.
             */}
            <div
              className={[
                "hidden min-h-11 flex-none items-center gap-1 px-2 py-1.5 lg:flex",
                rightOpen ? "border-b border-rail-line" : "",
              ].join(" ")}
            >
              <div
                className={[
                  "group/toggle hidden flex-none lg:block",
                  // Open: sits inline in the panel header.
                  // Collapsed: floats against the column's right edge, over the
                  // map's top-right corner (the column itself is now 0-width).
                  rightOpen
                    ? "relative"
                    : "lg:absolute lg:top-0.5 lg:right-1.5 lg:z-30",
                ].join(" ")}
              >
                {/*
                  * 44x44 hit area, 32x32 visual: the button stays the size the
                  * design wants while meeting the touch-target minimum every
                  * other control on the route already meets. Don't collapse
                  * these two boxes back into one.
                  */}
                <button
                  type="button"
                  onClick={() => setRightOpen((v) => !v)}
                  aria-expanded={rightOpen}
                  aria-label={rightOpen ? "Close sidebar" : "Open sidebar"}
                  className="flex h-11 w-11 items-center justify-center rounded-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
                >
                  <span
                    className={[
                      "flex h-8 w-8 items-center justify-center rounded-card transition-colors duration-150",
                      rightOpen
                        ? "text-slate-muted group-hover/toggle:bg-rail group-hover/toggle:text-ink"
                        : "border border-line-cool bg-surface-plain text-slate-muted shadow-float group-hover/toggle:text-ink",
                    ].join(" ")}
                  >
                    {rightOpen ? (
                      <PanelRightClose
                        aria-hidden="true"
                        strokeWidth={2}
                        className="h-[18px] w-[18px] flex-none"
                      />
                    ) : (
                      <PanelRightOpen
                        aria-hidden="true"
                        strokeWidth={2}
                        className="h-[18px] w-[18px] flex-none"
                      />
                    )}
                  </span>
                </button>
                <span
                  role="tooltip"
                  className="pointer-events-none absolute top-1/2 right-full mr-2 -translate-y-1/2 z-30 whitespace-nowrap rounded-card bg-ink px-2.5 py-1.5 text-[12px] font-medium text-white opacity-0 shadow-float transition-opacity duration-150 group-hover/toggle:opacity-100"
                >
                  {rightOpen ? "Close sidebar" : "Open sidebar"}
                </span>
              </div>
              {rightPanelSwitch && (
                <div
                  className={[
                    "ml-auto",
                    rightOpen ? "" : "hidden lg:hidden",
                  ].join(" ")}
                >
                  {rightPanelSwitch}
                </div>
              )}
            </div>

            <div
              className={[
                "min-h-0 flex-1 overflow-y-auto lg:overflow-x-hidden",
                rightOpen ? "" : "lg:hidden",
              ].join(" ")}
            >
              {rightPanel}
            </div>
          </section>
        )}
      </div>
    </APIProvider>
  );
}
