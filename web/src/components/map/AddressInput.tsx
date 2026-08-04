"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useMapsLibrary } from "@vis.gl/react-google-maps";
import type { LatLng } from "./MapPieces";

type Suggestion = { id: string; main: string; secondary: string };

/**
 * Address autocomplete built on the Places **Autocomplete Data API**
 * (`AutocompleteSuggestion.fetchAutocompleteSuggestions`) with our own input and
 * dropdown.
 *
 * Why not `PlaceAutocompleteElement`: that widget renders into a **closed**
 * shadow root, so no external CSS reaches it — not `::part()`, not custom
 * properties. It always looked like a Google control dropped into our bar
 * (Roboto, its own white pill, a blue Material focus ring). The Data API is the
 * supported way to build a custom UI and is still Places API (New) — this is not
 * a return to the deprecated `Autocomplete` class.
 *
 * Billing: a session token groups the keystrokes and the final `fetchFields`
 * into one billable session, same as the widget. A fresh token is minted after
 * each selection, which is what ends the session.
 */
export default function AddressInput({
  onPlace,
  /** Bias suggestions towards where the map is currently looking. */
  bias,
  placeholder = "Search a suburb or address",
}: {
  onPlace: (p: LatLng, label: string) => void;
  bias?: LatLng;
  placeholder?: string;
}) {
  const places = useMapsLibrary("places");
  const [text, setText] = useState("");
  const [items, setItems] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);

  const listId = useId();
  const boxRef = useRef<HTMLDivElement>(null);
  const tokenRef = useRef<google.maps.places.AutocompleteSessionToken | null>(
    null,
  );
  // Predictions are kept out of state: they're objects we only need on select,
  // and storing them would re-render on every keystroke for no benefit.
  const predictionsRef = useRef<google.maps.places.PlacePrediction[]>([]);

  useEffect(() => {
    if (!places) return;
    tokenRef.current = new places.AutocompleteSessionToken();
  }, [places]);

  // Debounced fetch. Every request is stamped so a slow earlier response can't
  // overwrite the results for what the user has since typed.
  useEffect(() => {
    if (!places || text.trim().length < 3) {
      setItems([]);
      predictionsRef.current = [];
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const { suggestions } =
          await places.AutocompleteSuggestion.fetchAutocompleteSuggestions({
            input: text,
            includedRegionCodes: ["au"],
            sessionToken: tokenRef.current ?? undefined,
            ...(bias
              ? { locationBias: { center: bias, radius: 30_000 } }
              : null),
          });
        if (cancelled) return;

        const preds = suggestions
          .map((s) => s.placePrediction)
          .filter((p): p is google.maps.places.PlacePrediction => p !== null);
        predictionsRef.current = preds;
        setItems(
          preds.map((p, i) => ({
            id: `${i}`,
            main: p.mainText?.toString() ?? p.text?.toString() ?? "",
            secondary: p.secondaryText?.toString() ?? "",
          })),
        );
        setActive(-1);
        setOpen(true);
      } catch {
        // A failed lookup shouldn't break the bar — the user can still drag the
        // pin, which is the primary way to choose a location anyway.
        if (!cancelled) setItems([]);
      }
    }, 250);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [places, text, bias]);

  // Close when focus or a click leaves the combobox.
  useEffect(() => {
    const onDocDown = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocDown);
    return () => document.removeEventListener("mousedown", onDocDown);
  }, []);

  const choose = async (i: number) => {
    const pred = predictionsRef.current[i];
    if (!pred || !places) return;
    setOpen(false);

    const place = pred.toPlace();
    await place.fetchFields({ fields: ["location", "formattedAddress"] });
    const loc = place.location;
    const label = place.formattedAddress ?? items[i]?.main ?? "";
    setText(label);
    if (loc) onPlace({ lat: loc.lat(), lng: loc.lng() }, label);

    // Selecting a place ends the billable session; the next keystroke starts a
    // new one.
    tokenRef.current = new places.AutocompleteSessionToken();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open || items.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % items.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a <= 0 ? items.length - 1 : a - 1));
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      void choose(active);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={boxRef} className="relative min-w-0 flex-1">
      <div className="flex min-w-0 items-center gap-2.5">
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          aria-hidden="true"
          className="flex-none text-slate-faint"
        >
          <circle
            cx="11"
            cy="11"
            r="7"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          />
          <path
            d="M16.5 16.5L21 21"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </svg>

        <input
          type="text"
          role="combobox"
          aria-expanded={open && items.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-label="Search a suburb or address"
          aria-activedescendant={
            active >= 0 ? `${listId}-${active}` : undefined
          }
          value={text}
          placeholder={placeholder}
          onChange={(e) => setText(e.target.value)}
          onFocus={() => items.length > 0 && setOpen(true)}
          onKeyDown={onKeyDown}
          /* No focus ring on the field itself — the bar around it is the
             control, and a ring inside a ring is what looked wrong. */
          className="min-w-0 flex-1 border-0 bg-transparent text-[13.5px] font-medium text-ink placeholder:font-normal placeholder:text-slate-faint focus:outline-none"
        />
      </div>

      {open && items.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="absolute top-[calc(100%+10px)] right-0 left-0 z-10 m-0 max-h-[280px] list-none overflow-y-auto rounded-panel border border-line-cool bg-surface-plain p-1 shadow-float"
        >
          {items.map((s, i) => (
            <li
              key={s.id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => {
                e.preventDefault(); // keep focus so blur doesn't close first
                void choose(i);
              }}
              className={[
                "cursor-pointer rounded-card px-3 py-2 text-[13px]",
                i === active ? "bg-paper-deep" : "",
              ].join(" ")}
            >
              <span className="font-medium text-ink">{s.main}</span>
              {s.secondary && (
                <span className="ml-1.5 text-[12px] text-slate-muted">
                  {s.secondary}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
