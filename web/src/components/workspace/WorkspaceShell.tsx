"use client";

import { useEffect, useState } from "react";
import { APIProvider, AdvancedMarker, Map } from "@vis.gl/react-google-maps";
import { listSearches, type Me, type SearchSummary } from "@/lib/api";
import { RadiusCircle, type LatLng } from "../map/MapPieces";
import Rail from "./Rail";

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY!;

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
  topBar,
  mapOverlay,
  floatingPanel,
  stackedPanel,
  rightPanel,
  rightPanelTitle,
  rightPanelSwitch,
  onNewSearch,
}: {
  me: Me;
  center: LatLng;
  radiusKm: number;
  onCenterChange?: (p: LatLng) => void;
  /** Only the workspace lets you move the pin; results are a fixed record. */
  draggablePin?: boolean;
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
  onNewSearch: () => void;
}) {
  const [recent, setRecent] = useState<SearchSummary[]>([]);
  const [loadingRecent, setLoadingRecent] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);

  useEffect(() => {
    listSearches()
      .then(setRecent)
      .catch(() => setRecent([]))
      .finally(() => setLoadingRecent(false));
  }, []);

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
          />
        </aside>

        {/* ── The map, and everything floating on it ──────────────────── */}
        <div className="relative order-1 h-[380px] flex-none overflow-hidden bg-paper-deep lg:order-none lg:h-auto lg:flex-1">
          <Map
            defaultZoom={13}
            center={center}
            mapId="fmaj-search"
            className="h-full w-full"
            onClick={(e) => e.detail.latLng && onCenterChange?.(e.detail.latLng)}
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
          </Map>

          <div className="absolute top-4 right-4 left-4 sm:right-5 sm:left-5">
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
              "order-2 flex flex-col border-rail-line bg-surface-plain",
              "border-t lg:order-none lg:border-t-0 lg:border-l",
              rightOpen ? "lg:w-[330px]" : "lg:w-[44px]",
              "lg:flex-none lg:overflow-hidden lg:transition-[width] lg:duration-200",
            ].join(" ")}
          >
            {/*
             * Collapsing is a >=lg affordance. Below that the panel is just the
             * next block in the page and hiding it behind a 44px strip would
             * only hide the content the user came for.
             */}
            <div className="hidden flex-none items-center gap-1 border-b border-rail-line px-2 py-1.5 lg:flex">
              <button
                type="button"
                onClick={() => setRightOpen((v) => !v)}
                aria-expanded={rightOpen}
                aria-label={
                  rightOpen ? "Hide this panel" : "Show this panel"
                }
                className="flex flex-none items-center gap-1.5 rounded-card px-1.5 py-1 hover:bg-rail focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                  className={[
                    "flex-none text-slate-faint transition-transform duration-200",
                    rightOpen ? "" : "rotate-180",
                  ].join(" ")}
                >
                  <path
                    d="M9 6l6 6-6 6"
                    stroke="currentColor"
                    strokeWidth="2.2"
                    fill="none"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                {rightOpen && (
                  <span className="text-[11px] font-semibold text-slate-muted">
                    Hide
                  </span>
                )}
              </button>
              {rightOpen && rightPanelSwitch && (
                <div className="ml-auto">{rightPanelSwitch}</div>
              )}
            </div>

            <div
              className={[
                "min-h-0 flex-1 overflow-y-auto",
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
