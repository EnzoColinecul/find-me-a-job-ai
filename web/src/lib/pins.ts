/**
 * Spread co-located result pins so none is hidden behind another.
 *
 * Two venues in the same arcade (or two entries Places returns for the same
 * building) land within metres of each other, and at the camera that fits the
 * search radius that is well under one pin's width — the search this was first
 * observed on had five of thirteen pins stacked into a single blob over the
 * word "Melbourne".
 *
 * The offset is applied in **pixels**, as a CSS translate on the badge, not as
 * a nudge to the coordinate: a geographic offset would look right at one zoom
 * and be metres out at another, and it would put the marker somewhere the
 * business isn't. The anchor stays truthful; only the badge steps aside, and
 * `NumberedPin` draws a hairline back to the real point.
 */

export interface PinPoint {
  lat: number;
  lng: number;
}

/** Pin diameter plus a little breathing room, in CSS px. */
const PIN_PX = 28;

/** A pin never wanders further than this from its real point. */
const MAX_OFFSET_PX = PIN_PX * 2.5;

/** Enough passes to settle a couple of dozen pins; the loop exits early. */
const MAX_PASSES = 80;

export interface FannedPin<T> {
  item: T;
  /** CSS pixel offset to apply to the pin. Zero for a pin that stands alone. */
  offset: { x: number; y: number };
}

/**
 * Push overlapping pins apart until every pair clears `PIN_PX`.
 *
 * This replaced a cheaper "group by proximity, fan each group onto a ring"
 * pass, which had a flaw worth not reintroducing: groups were formed greedily
 * against whichever member came first, so two *adjacent* groups could each be
 * internally tidy and still collide with each other — which is exactly what
 * four pins around Melbourne Town Hall did. Relaxation has no notion of groups,
 * so there is nothing for a pair to fall between.
 *
 * Work happens in a local metre plane (equirectangular about the first point —
 * fine over the few hundred metres in play) and only the *displacement* is
 * converted to pixels. Order is preserved, so the caller's numbering is
 * untouched, and the result is deterministic: the same list always settles the
 * same way, so pins don't dance between renders.
 */
export function fanOutPins<T extends PinPoint>(
  items: T[],
  /**
   * Ground metres per CSS pixel at the camera these pins will be seen at —
   * `metresPerPixel(radiusKm, mapShorterEdgePx)` from `MapPieces`. It must be
   * the *measured* scale, not a nominal one: a 380px-tall phone map is roughly
   * 1.6x tighter than a desktop column, and pins separated for the desktop
   * still overlap there.
   */
  mPerPx: number,
): Array<FannedPin<T>> {
  if (items.length < 2) {
    return items.map((item) => ({ item, offset: { x: 0, y: 0 } }));
  }

  const minSep = PIN_PX * mPerPx;
  const maxOffset = MAX_OFFSET_PX * mPerPx;

  const R = 6371000;
  const origin = items[0];
  const cosLat = Math.cos((origin.lat * Math.PI) / 180);
  const toPlane = (p: PinPoint) => ({
    x: (((p.lng - origin.lng) * Math.PI) / 180) * R * cosLat,
    y: (((p.lat - origin.lat) * Math.PI) / 180) * R,
  });

  const anchors = items.map(toPlane);
  // Exactly co-located points have no axis to separate along, so seed each with
  // a distinct sub-metre nudge. Derived from the index, so it's reproducible.
  const positions = anchors.map((p, i) => {
    const angle = (2 * Math.PI * i) / items.length - Math.PI / 2;
    const seed = minSep * 0.01;
    return { x: p.x + Math.cos(angle) * seed, y: p.y + Math.sin(angle) * seed };
  });

  for (let pass = 0; pass < MAX_PASSES; pass += 1) {
    let moved = false;
    for (let i = 0; i < positions.length; i += 1) {
      for (let j = i + 1; j < positions.length; j += 1) {
        const dx = positions[j].x - positions[i].x;
        const dy = positions[j].y - positions[i].y;
        const d = Math.hypot(dx, dy);
        if (d >= minSep) continue;
        const push = (minSep - d) / 2;
        const ux = d > 0 ? dx / d : 0;
        const uy = d > 0 ? dy / d : 1;
        positions[i].x -= ux * push;
        positions[i].y -= uy * push;
        positions[j].x += ux * push;
        positions[j].y += uy * push;
        moved = true;
      }
    }
    if (!moved) break;

    // Re-anchor: a pin that has drifted too far is pulled back toward its real
    // point. This is what keeps the whole set from slowly inflating outward.
    for (let i = 0; i < positions.length; i += 1) {
      const dx = positions[i].x - anchors[i].x;
      const dy = positions[i].y - anchors[i].y;
      const d = Math.hypot(dx, dy);
      if (d > maxOffset) {
        positions[i].x = anchors[i].x + (dx / d) * maxOffset;
        positions[i].y = anchors[i].y + (dy / d) * maxOffset;
      }
    }
  }

  return items.map((item, i) => {
    const dx = (positions[i].x - anchors[i].x) / mPerPx;
    // Screen y grows downward; the plane's y grows north.
    const dy = -(positions[i].y - anchors[i].y) / mPerPx;
    const offset = { x: Math.round(dx), y: Math.round(dy) };
    // Sub-pixel drift isn't worth a leader line.
    return Math.abs(offset.x) < 2 && Math.abs(offset.y) < 2
      ? { item, offset: { x: 0, y: 0 } }
      : { item, offset };
  });
}
