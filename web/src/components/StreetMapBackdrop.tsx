/**
 * The stylised street map that sits behind the login and home screens.
 *
 * Purely decorative — it is not the real Google map, and it is hidden from
 * assistive tech. Ported from `design/mockups-extracted.html` with every colour
 * pulled from the token layer rather than hardcoded.
 *
 * Each mockup screen tunes it differently, so the knobs are props rather than
 * baked in: login is rotated -7deg and blurred behind its card, home is -4deg
 * with a stronger wash (the greeting sits directly on the map, so the map has
 * to recede further).
 *
 * It drifts slowly via the `mapPan` keyframes; `prefers-reduced-motion` in
 * globals.css freezes it.
 */

type Poi = { left: string; top: string; label: string; color: string };
type Street = { left: string; top: string; rotate: string; label: string };

const POIS: Poi[] = [
  { left: "21%", top: "17%", label: "Town Hall", color: "var(--color-chip-purple)" },
  { left: "45%", top: "48%", label: "Cafe Rosa", color: "var(--color-warn)" },
  { left: "69%", top: "35%", label: "Skate Park", color: "var(--color-success)" },
  { left: "30%", top: "71%", label: "The Dolphin", color: "var(--color-chip-pink)" },
  { left: "52%", top: "63%", label: "Arts Centre", color: "var(--color-chip-purple)" },
  { left: "36%", top: "39%", label: "Market Hall", color: "var(--color-warn)" },
  { left: "76%", top: "50%", label: "Riverside", color: "var(--color-success)" },
  { left: "58%", top: "14%", label: "Grand Hotel", color: "var(--color-chip-pink)" },
  { left: "14%", top: "42%", label: "Central Stn", color: "var(--color-accent)" },
];

const STREETS: Street[] = [
  { left: "5%", top: "20%", rotate: "-1deg", label: "Bourke St" },
  { left: "40%", top: "12%", rotate: "-1deg", label: "Spring St" },
  { left: "19%", top: "33%", rotate: "-1deg", label: "Collins St" },
  { left: "56%", top: "26%", rotate: "-1deg", label: "Flinders Ln" },
  { left: "9%", top: "72%", rotate: "-6deg", label: "Southbank Blvd" },
  { left: "41%", top: "88%", rotate: "3deg", label: "St Kilda Rd" },
];

const BUILDINGS = [
  { left: "20%", top: "22%", w: "16px", h: "10px", r: "-1deg" },
  { left: "24%", top: "26%", w: "10px", h: "14px", r: "-1deg" },
  { left: "15%", top: "15%", w: "14px", h: "9px", r: "-1deg" },
  { left: "28%", top: "17%", w: "12px", h: "12px", r: "-1deg" },
  { left: "45%", top: "26%", w: "13px", h: "9px", r: "2deg" },
  { left: "49%", top: "33%", w: "10px", h: "11px", r: "2deg" },
  { left: "60%", top: "66%", w: "14px", h: "10px", r: "-4deg" },
  { left: "64%", top: "71%", w: "11px", h: "12px", r: "-4deg" },
];

const ROAD_EDGE = "0 -1.5px 0 var(--color-line), 0 1.5px 0 var(--color-line)";
const ROAD_EDGE_V = "-1.5px 0 0 var(--color-line), 1.5px 0 0 var(--color-line)";

export type BackdropProps = {
  /** Rotation of the street grid, in degrees. Login -7, home -4. */
  rotate?: number;
  /** How far the drifting layer bleeds past the frame, in px. */
  spread?: number;
  /** Drift cycle, in seconds. */
  duration?: number;
  /** Blur radius in px; 0 for a crisp map. */
  blur?: number;
  /**
   * `light` — the login's gentle wash, for a map behind a solid card.
   * `strong` — the home's three-stop wash, for text sitting on the map itself.
   */
  wash?: "light" | "strong";
};

export default function StreetMapBackdrop({
  rotate = -7,
  spread = 80,
  duration = 24,
  blur = 2,
  wash = "light",
}: BackdropProps) {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 overflow-hidden bg-paper-deep select-none"
    >
      <div
        className="absolute overflow-hidden"
        style={{
          inset: `-${spread}px`,
          animation: `mapPan ${duration}s ease-in-out infinite`,
          filter: blur ? `blur(${blur}px)` : undefined,
        }}
      >
        <div
          className="absolute -inset-[22%] origin-center overflow-hidden"
          style={{ transform: `rotate(${rotate}deg)` }}
        >
          {/* Land masses */}
          <div className="absolute inset-0 bg-paper-deep" />
          <div className="absolute -left-[12%] -top-[12%] h-1/2 w-2/3 bg-map-block" />
          <div
            className="absolute left-[63%] -top-[8%] h-[46%] w-[52%] bg-map-park"
            style={{ borderRadius: "42% 58% 50% 50% / 48% 42% 58% 52%" }}
          />
          <div
            className="absolute left-[56%] top-[60%] h-[58%] w-[62%] bg-map-park"
            style={{ borderRadius: "50% 45% 40% 55% / 45% 55% 45% 55%" }}
          />
          <div className="absolute left-[17%] top-[74%] h-[11%] w-[13%] rounded-card bg-map-park-soft" />
          <div className="absolute left-[38%] top-[20%] h-[6%] w-[7%] rounded-md bg-map-park-faint" />

          {/* Street grid */}
          <div
            className="absolute inset-0"
            style={{
              backgroundImage:
                "repeating-linear-gradient(90deg,transparent 0 13px,rgb(255 255 255 / 0.4) 13px 14px)," +
                "repeating-linear-gradient(0deg,transparent 0 13px,rgb(255 255 255 / 0.4) 13px 14px)",
            }}
          />
          <div
            className="absolute inset-0"
            style={{
              backgroundImage:
                "repeating-linear-gradient(90deg,transparent 0 39px,rgb(255 255 255 / 0.95) 39px 41.5px)," +
                "repeating-linear-gradient(0deg,transparent 0 45px,rgb(255 255 255 / 0.95) 45px 47.5px)",
            }}
          />

          {/* Water */}
          <div className="absolute -left-[20%] top-1/2 h-[6%] w-[92%] rotate-[4deg] rounded-card bg-map-water" />
          <div className="absolute left-[54%] top-[44%] h-[6%] w-[82%] -rotate-[11deg] rounded-card bg-map-water" />

          {/* Arterial roads */}
          <div
            className="absolute -left-[20%] top-[29%] h-2.5 w-[140%] bg-map-road"
            style={{ boxShadow: ROAD_EDGE }}
          />
          <div
            className="absolute -left-[20%] top-[57%] h-2 w-[140%] rotate-[2deg] bg-map-road"
            style={{ boxShadow: ROAD_EDGE }}
          />
          <div
            className="absolute left-[33%] -top-[20%] h-[140%] w-2.5 bg-map-road"
            style={{ boxShadow: ROAD_EDGE_V }}
          />
          <div
            className="absolute left-[71%] -top-[20%] h-[140%] w-2 -rotate-[4deg] bg-map-road"
            style={{ boxShadow: ROAD_EDGE_V }}
          />
          <div
            className="absolute -left-[12%] top-[70%] h-[9px] w-[132%] -rotate-[6deg] bg-map-road"
            style={{ boxShadow: ROAD_EDGE }}
          />
          <div
            className="absolute -left-[16%] top-[84%] h-[13px] w-[140%] rotate-[3deg] bg-map-highway"
            style={{
              boxShadow:
                "0 -2px 0 var(--color-map-highway-edge), 0 2px 0 var(--color-map-highway-edge)",
            }}
          />

          {/* Rail lines */}
          <div
            className="absolute left-[11%] -top-[10%] h-[130%] w-[3px] rotate-[9deg]"
            style={{
              background:
                "repeating-linear-gradient(180deg,var(--color-map-rail) 0 6px,transparent 6px 11px)",
            }}
          />
          <div
            className="absolute -left-[10%] top-[38%] h-0.5 w-[130%] -rotate-[3deg]"
            style={{
              background:
                "repeating-linear-gradient(90deg,var(--color-map-rail) 0 6px,transparent 6px 11px)",
            }}
          />

          {/* City blocks */}
          {BUILDINGS.map((b, i) => (
            <div
              key={i}
              className="absolute rounded-tag bg-map-building"
              style={{
                left: b.left,
                top: b.top,
                width: b.w,
                height: b.h,
                transform: `rotate(${b.r})`,
              }}
            />
          ))}

          {/* Street names — decorative, so ink-muted is acceptable here */}
          {STREETS.map((s) => (
            <div
              key={s.label}
              className="absolute whitespace-nowrap text-[8.5px] font-semibold text-ink-muted"
              style={{ left: s.left, top: s.top, transform: `rotate(${s.rotate})` }}
            >
              {s.label}
            </div>
          ))}
          <div className="absolute left-[20%] top-[54%] rotate-[4deg] whitespace-nowrap text-[9px] font-semibold text-map-water">
            Río Verde
          </div>
          <div className="absolute left-[74%] top-[18%] whitespace-nowrap text-[9px] font-semibold text-success-deep">
            Fitzroy Gardens
          </div>
          <div className="absolute left-[66%] top-[76%] whitespace-nowrap text-[9px] font-semibold text-success-deep">
            Kings Domain
          </div>

          {/* Route shields */}
          {[
            { left: "46%", top: "31%", label: "30" },
            { left: "24%", top: "85%", label: "M1" },
            { left: "64%", top: "59%", label: "20" },
          ].map((r) => (
            <div
              key={r.label}
              className="absolute rounded-[3px] bg-accent px-[3px] py-px text-[7.5px] font-bold text-white ring-[1.5px] ring-white"
              style={{ left: r.left, top: r.top }}
            >
              {r.label}
            </div>
          ))}

          {/* Points of interest */}
          {POIS.map((p) => (
            <div
              key={p.label}
              className="absolute flex items-center gap-[3px]"
              style={{ left: p.left, top: p.top }}
            >
              <span
                className="h-[11px] w-[11px] flex-none rounded-full ring-2 ring-white"
                style={{ background: p.color }}
              />
              <span
                className="whitespace-nowrap text-[8px] font-semibold"
                style={{ color: p.color }}
              >
                {p.label}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Wash that lifts the foreground off the map */}
      <div
        className="absolute inset-0"
        style={{
          background:
            wash === "strong"
              ? "linear-gradient(180deg, rgb(255 255 255 / 0.08) 0%, rgb(255 255 255 / 0.34) 55%, rgb(255 255 255 / 0.62) 100%)"
              : "linear-gradient(180deg, rgb(255 255 255 / 0.12), rgb(255 255 255 / 0.42))",
        }}
      />
    </div>
  );
}
