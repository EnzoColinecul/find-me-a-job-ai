"use client";

import { listSearches, type Me, type SearchSummary } from "@/lib/api";
import { APIProvider, AdvancedMarker, Map } from "@vis.gl/react-google-maps";
import { PanelRightClose, PanelRightOpen } from "lucide-react";
import { useEffect, useState } from "react";
import { RadiusCircle, type LatLng } from "../map/MapPieces";
import Rail from "./Rail";

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY!;

/**
 * The numbered badge dropped on the map for each result. All pins use
 * `--accent-strong` (blue), matching the card numbers. Hovering a card enlarges
 * its pin and rings it so the eye can find it.
 */
function NumberedPin({
  index,
  highlighted,
}: {
  index: number;
  highlighted: boolean;
}) {
  return (
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

  return (
    <APIProvider apiKey={MAPS_KEY}>
      <div className="flex min-h-dvh flex-col bg-surface-plain lg:h-dvh lg:flex-row lg:overflow-hidden">
        <aside className="order-3 border-t border-rail-line bg-rail lg:order-none lg:w-[216px] lg:flex-none lg:overflow-y-auto lg:border-t-0 lg:border-r">
          <Rail
            me={me}
            recent={recent}
            loadingRecent={loadingRecent}
            onNewSearch={onNewSearch}
            newSearchDisabledReason={newSearchDisabledReason}
          />
        </aside>

        {/* ── The map, and everything floating on it ──────────────────── */}
        <div className="relative order-1 h-[380px] flex-none overflow-hidden bg-paper-deep lg:order-none lg:h-auto lg:flex-1">
          <Map
            defaultZoom={13}
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

            {/* Numbered result pins (mockup 4). zIndex lifts the highlighted one
                and the featured #1 above the rest so they can't be hidden. */}
            {markers?.map((m) => (
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
                />
              </AdvancedMarker>
            ))}
          </Map>

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
          <div className="order-2 border-b border-rail-line bg-surface-plain px-5 py-5 lg:hidden">
            {stackedPanel}
          </div>
        )}

        {/* ── Results column ──────────────────────────────────────────── */}
        {hasRight && (
          <section
            aria-label={rightPanelTitle ?? "Results"}
            className={[
              // Mobile: a normal stacked block with the panel surface.
              "order-2 flex flex-col border-t border-rail-line bg-surface-plain",
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
                    : "lg:absolute lg:top-2 lg:right-3 lg:z-30",
                ].join(" ")}
              >
                <button
                  type="button"
                  onClick={() => setRightOpen((v) => !v)}
                  aria-expanded={rightOpen}
                  aria-label={rightOpen ? "Close sidebar" : "Open sidebar"}
                  className={[
                    "flex h-8 w-8 items-center justify-center rounded-card transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong",
                    rightOpen
                      ? "text-slate-muted hover:bg-rail hover:text-ink"
                      : "border border-line-cool bg-surface-plain text-slate-muted shadow-float hover:text-ink",
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
