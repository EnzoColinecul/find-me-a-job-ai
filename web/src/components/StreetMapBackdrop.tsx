const ZOOM = 0.8;

const VIEW_W = 1200;
const VIEW_H = 800;
const CX = VIEW_W / 2;
const CY = VIEW_H / 2;

/** Angle of the damero relative to the scene, in degrees. */
const GRID_ANGLE = -31;

/* ---------------------------------------------------------------- grids -- */

/** Block pitch, in viewBox units. ~100 m blocks at zoom 15. */
const S = 40;

const GRID_X = Array.from({ length: 76 }, (_, i) => -800 + i * S);
const GRID_Y = Array.from({ length: 56 }, (_, i) => -600 + i * S);

/** Every fifth line is an avenida — wider, and the ones that carry a name. */
const isAvenida = (v: number) => (((v - 120) % 200) + 200) % 200 === 0;

type StreetLabel = { at: number; along: number; label: string };

/** Streets running along the grid's local X axis. */
const STREETS_EW: StreetLabel[] = [
  { at: 120, along: 900, label: "Av. Ameghino" },
  { at: 200, along: 620, label: "Sarmiento" },
  { at: 240, along: 520, label: "Rivadavia" },
  { at: 320, along: 470, label: "Av. Fontana" },
  { at: 360, along: 900, label: "25 de Mayo" },
  { at: 440, along: 700, label: "San Martín" },
  { at: 560, along: 640, label: "Mitre" },
  { at: 640, along: 300, label: "Belgrano" },
  { at: 680, along: 360, label: "9 de Julio" },
];

/** Streets running along the grid's local Y axis. */
const STREETS_NS: StreetLabel[] = [
  { at: 120, along: 600, label: "Av. Perito Moreno" },
  { at: 240, along: 300, label: "Chacabuco" },
  { at: 320, along: 660, label: "Av. Roca" },
  { at: 440, along: 560, label: "Pellegrini" },
  { at: 520, along: 580, label: "Alberdi" },
  { at: 640, along: 640, label: "Almafuerte" },
  { at: 720, along: 680, label: "O'Higgins" },
  { at: 840, along: 340, label: "Volta" },
];

/** Commercial frontage — Google tints these blocks pale yellow. */
const COMERCIO = [
  [280, 380],
  [320, 380],
  [360, 380],
  [400, 380],
  [320, 420],
  [360, 420],
  [400, 300],
  [440, 300],
];

/** Denser built form through the centro. */
const BUILDINGS = [
  [332, 252],
  [372, 252],
  [452, 292],
  [492, 332],
  [372, 452],
  [412, 332],
  [332, 492],
  [452, 452],
  [532, 372],
  [572, 452],
  [292, 332],
  [612, 332],
  [412, 492],
  [492, 532],
  [572, 292],
  [252, 292],
  [652, 412],
  [532, 572],
  [292, 572],
  [372, 612],
  [612, 532],
  [692, 292],
  [252, 452],
  [692, 492],
];

/* ------------------------------------------------------- barrio Estación -- */

/**
 * Estación predates the damero — it grew around the railway yard — so its
 * streets wander instead of gridding. Grid-local coordinates. The damero is
 * masked out of this outline rather than painted over, so the barrio sits on
 * the same ground as the rest of town and its streets are drawn in the same
 * road colour and weight — the wandering pattern is the only thing marking it
 * out, with no boundary drawn.
 */
const ESTACION_OUTLINE = "M 250 -120 L 570 -90 L 560 120 L 300 140 Z";

const ESTACION_STREETS = [
  "M 236 -48 C 322 -72 402 -62 472 -80 C 520 -93 548 -87 580 -80",
  "M 250 12 C 338 -10 420 0 500 -17 C 536 -25 552 -23 580 -19",
  "M 268 84 C 348 60 430 66 500 50 C 530 44 548 46 574 48",
  "M 258 -96 C 330 -112 400 -104 452 -116",
  "M 300 40 C 350 20 400 40 440 10 C 470 -12 500 -6 540 -20",
  "M 322 -126 C 314 -52 324 10 310 80 C 306 104 304 122 302 146",
  "M 386 -120 C 380 -42 390 20 378 90 C 374 110 372 124 370 146",
  "M 470 -114 C 464 -42 474 14 466 86 C 462 106 460 118 458 138",
  "M 528 -106 C 524 -42 532 10 524 62",
];

const ESTACION_LABELS: { x: number; y: number; r: number; label: string }[] = [
  { x: 268, y: -56, r: 0, label: "Bandurria" },
  { x: 288, y: 4, r: 0, label: "Roberts" },
  { x: 306, y: 64, r: 0, label: "Mara" },
  { x: 410, y: -108, r: 90, label: "Cóndor" },
  { x: 478, y: -102, r: 90, label: "Desalojo del 37" },
];

/** Blocks inside the barrio, same treatment as the rest of the built form. */
const ESTACION_BUILDINGS = [
  [300, -70],
  [344, -28],
  [380, -92],
  [430, -38],
  [470, 18],
  [350, 58],
  [502, -68],
  [282, 38],
];

/* ------------------------------------------------------------- overlays -- */

/**
 * Through town the national route *is* Av. Alvear, so it runs on the grid like
 * any other street rather than cutting across it. This is its grid-local line;
 * it is drawn outside the town clip so it carries on into the countryside.
 */
const RUTA_Y = 520;

/** Grid-local x positions for the route shields. */
const RUTA_SHIELDS = [420, 1020];

type Barrio = { x: number; y: number; lines: string[] };

/** Neighbourhood names, set in spaced caps the way the real tiles do. */
const BARRIOS: Barrio[] = [
  { x: -50, y: 265, lines: ["CAÑADÓN", "DE BORQUEZ"] },
  { x: 210, y: 110, lines: ["ESTACIÓN"] },
  { x: 1235, y: 85, lines: ["TRES SARGENTOS"] },
  { x: 610, y: 60, lines: ["BELLA VISTA"] },
  { x: 124, y: 520, lines: ["DR WINTER"] },
  { x: 470, y: 170, lines: ["GRAL JULIO", "A. ROCA"] },
  { x: 790, y: 300, lines: ["MEDARDO", "MORELLI"] },
  { x: 215, y: 445, lines: ["DON BOSCO"] },
  { x: 195, y: 575, lines: ["BELGRANO"] },
  { x: 455, y: 620, lines: ["CENTRO"] },
  { x: 1020, y: 470, lines: ["28 DE JUNIO"] },
  { x: 950, y: 620, lines: ["SGTO CABRAL"] },
  { x: 300, y: 740, lines: ["GRAL SAN MARTÍN"] },
  { x: 610, y: 880, lines: ["ANTÁRTIDA"] },
  { x: 1010, y: 855, lines: ["BARRIO CEFERINO"] },
];

type Poi = { x: number; y: number; label: string; color: string };

const POIS: Poi[] = [
  { x: 116, y: 372, label: "La Trochita", color: "var(--color-accent)" },
  { x: 380, y: 330, label: "Supermercado Norte", color: "var(--color-warn)" },
  {
    x: 700,
    y: 120,
    label: "Terminal de Ómnibus",
    color: "var(--color-chip-pink)",
  },
  { x: 330, y: 470, label: "Municipalidad", color: "var(--color-chip-purple)" },
  { x: 690, y: 470, label: "Café del Sur", color: "var(--color-warn)" },
  {
    x: 470,
    y: 690,
    label: "Hotel Argentino",
    color: "var(--color-chip-purple)",
  },
  { x: 180, y: 660, label: "Panadería Roca", color: "var(--color-chip-pink)" },
  { x: 855, y: 700, label: "Hospital Zonal", color: "var(--color-success)" },
  {
    x: 1105,
    y: 390,
    label: "Estación de Servicio",
    color: "var(--color-warn)",
  },
  {
    x: 115,
    y: 700,
    label: "Ferretería Andina",
    color: "var(--color-chip-purple)",
  },
];

/* ----------------------------------------------------------------- props -- */

export type BackdropProps = {
  /** Rotation of the whole map scene, in degrees. Login -7, home -4. */
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
  blur = 4,
  wash = "light",
}: BackdropProps) {
  /** Keeps a glyph upright while its anchor rides the rotated scene. */
  const upright = (x: number, y: number) =>
    `translate(${x} ${y}) rotate(${-rotate}) scale(${1 / ZOOM})`;

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
        <svg
          className="h-full w-full"
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          preserveAspectRatio="xMidYMid slice"
          focusable="false"
        >
          <defs>
            {/* The grid stops at the edge of town; beyond it is countryside. */}
            <clipPath id="smb-town">
              <path d="M-140 250 C60 150 260 80 520 40 C760 4 1000 -30 1340 -60 L1340 620 C1180 700 1010 760 800 810 C560 866 300 880 -140 856 Z" />
            </clipPath>
            <clipPath id="smb-estacion">
              <path d={ESTACION_OUTLINE} />
            </clipPath>
            {/*
              Punches Estación out of the damero. Black and white here are
              mask luminance values, not palette colours — white keeps, black
              drops.
            */}
            <mask
              id="smb-damero"
              maskUnits="userSpaceOnUse"
              x={-3000}
              y={-3000}
              width={8000}
              height={8000}
            >
              <rect
                x={-3000}
                y={-3000}
                width={8000}
                height={8000}
                fill="#fff"
              />
              <path d={ESTACION_OUTLINE} fill="#000" />
            </mask>
          </defs>

          <g
            transform={
              `rotate(${rotate} ${CX} ${CY}) ` +
              `translate(${CX} ${CY}) scale(${ZOOM}) translate(${-CX} ${-CY})`
            }
          >
            {/* ------------------------------------------- countryside -- */}
            <rect
              x="-500"
              y="-500"
              width="2200"
              height="1800"
              fill="var(--color-map-block)"
            />

            {/* ---------------------------------------------- the town -- */}
            <g clipPath="url(#smb-town)">
              <rect
                x="-500"
                y="-500"
                width="2200"
                height="1800"
                fill="var(--color-paper-deep)"
              />

              <g transform={`rotate(${GRID_ANGLE} ${CX} ${CY})`}>
                <g mask="url(#smb-damero)">
                  {/* Commercial frontage through the centro. */}
                  {COMERCIO.map(([x, y]) => (
                    <rect
                      key={`k${x}-${y}`}
                      x={x}
                      y={y}
                      width={S}
                      height={S}
                      fill="var(--color-map-block)"
                    />
                  ))}

                  {/* Plaza San Martín and the two barrio squares. */}
                  <rect
                    x={480}
                    y={400}
                    width={S}
                    height={S}
                    fill="var(--color-map-park-soft)"
                  />
                  <rect
                    x={240}
                    y={560}
                    width={S}
                    height={S}
                    fill="var(--color-map-park-faint)"
                  />
                  <rect
                    x={720}
                    y={240}
                    width={S}
                    height={S}
                    fill="var(--color-map-park-faint)"
                  />

                  {/* Streets. */}
                  {GRID_X.map((x) => (
                    <line
                      key={`gx${x}`}
                      x1={x}
                      y1={-620}
                      x2={x}
                      y2={1620}
                      stroke="var(--color-map-road)"
                      strokeWidth={isAvenida(x) ? 7 : 3.4}
                    />
                  ))}
                  {GRID_Y.map((y) => (
                    <line
                      key={`gy${y}`}
                      x1={-820}
                      y1={y}
                      x2={2260}
                      y2={y}
                      stroke="var(--color-map-road)"
                      strokeWidth={isAvenida(y) ? 7 : 3.4}
                    />
                  ))}

                  {/* Built form. */}
                  {BUILDINGS.map(([x, y]) => (
                    <rect
                      key={`b${x}-${y}`}
                      x={x}
                      y={y}
                      width={22}
                      height={16}
                      rx={2}
                      fill="var(--color-map-building)"
                    />
                  ))}
                </g>

                {/* Street names, riding their own street. */}
                {STREETS_EW.map((s) => (
                  <text
                    key={s.label}
                    x={s.along}
                    y={s.at - 4}
                    fontSize={(isAvenida(s.at) ? 11 : 9.5) / ZOOM}
                    fontWeight="600"
                    fill="var(--color-ink-muted)"
                  >
                    {s.label}
                  </text>
                ))}
                {STREETS_NS.map((s) => (
                  <text
                    key={s.label}
                    transform={`translate(${s.at + 4} ${s.along}) rotate(90)`}
                    fontSize={(isAvenida(s.at) ? 11 : 9.5) / ZOOM}
                    fontWeight="600"
                    fill="var(--color-ink-muted)"
                  >
                    {s.label}
                  </text>
                ))}
              </g>
            </g>

            {/* ---------------------------------------- barrio Estación -- */}
            <g transform={`rotate(${GRID_ANGLE} ${CX} ${CY})`}>
              <g clipPath="url(#smb-estacion)">
                {ESTACION_STREETS.map((d) => (
                  <path
                    key={d}
                    d={d}
                    fill="none"
                    stroke="var(--color-map-road)"
                    strokeWidth={3.4}
                    strokeLinecap="round"
                  />
                ))}
                {ESTACION_BUILDINGS.map(([x, y]) => (
                  <rect
                    key={`e${x}-${y}`}
                    x={x}
                    y={y}
                    width={20}
                    height={14}
                    rx={2}
                    fill="var(--color-map-building)"
                  />
                ))}
              </g>
              {ESTACION_LABELS.map((l) => (
                <text
                  key={l.label}
                  transform={`translate(${l.x} ${l.y}) rotate(${l.r})`}
                  fontSize={8.5 / ZOOM}
                  fontWeight="600"
                  fill="var(--color-ink-muted)"
                >
                  {l.label}
                </text>
              ))}
            </g>

            {/* ------------------------------------ cemetery + scrubland -- */}
            <ellipse
              cx={1108}
              cy={168}
              rx={104}
              ry={62}
              fill="var(--color-map-park)"
              transform="rotate(-24 1108 168)"
            />
            <path
              d="M1340 900 L1340 700 C1180 754 1060 826 992 900 Z"
              fill="var(--color-map-park)"
            />

            {/* ------------------------------------------ Arroyo Esquel -- */}
            <path
              d="M540 880 C680 800 780 742 900 716 C1010 692 1120 706 1300 690"
              fill="none"
              stroke="var(--color-map-water)"
              strokeWidth={4}
              strokeLinecap="round"
            />

            {/* --------------------------------------------------- RN 259 -- */}
            <g transform={`rotate(${GRID_ANGLE} ${CX} ${CY})`}>
              <line
                x1={-820}
                y1={RUTA_Y}
                x2={2260}
                y2={RUTA_Y}
                stroke="var(--color-map-highway-edge)"
                strokeWidth={17}
              />
              <line
                x1={-820}
                y1={RUTA_Y}
                x2={2260}
                y2={RUTA_Y}
                stroke="var(--color-map-highway)"
                strokeWidth={13}
              />
              {/* Rides the route the way the other street names ride theirs. */}
              <text
                x={420}
                y={RUTA_Y - 16}
                fontSize={11 / ZOOM}
                fontWeight="600"
                fill="var(--color-ink-muted)"
              >
                Av. Alvear
              </text>
            </g>

            {/* ------------------------------------------ upright labels -- */}
            {BARRIOS.map((b) => (
              <text
                key={b.lines.join(" ")}
                transform={upright(b.x, b.y)}
                fontSize={12}
                fontWeight="700"
                letterSpacing="1.1"
                textAnchor="middle"
                fill="var(--color-ink-muted)"
              >
                {b.lines.map((line, i) => (
                  <tspan key={line} x={0} dy={i === 0 ? 0 : 15}>
                    {line}
                  </tspan>
                ))}
              </text>
            ))}

            <text
              transform={upright(640, 385)}
              fontSize={18}
              fontWeight="700"
              textAnchor="middle"
              fill="var(--color-ink-soft)"
            >
              Esquel
            </text>

            <g transform={`rotate(${GRID_ANGLE} ${CX} ${CY})`}>
              {RUTA_SHIELDS.map((x) => (
                <g
                  key={x}
                  transform={`translate(${x} ${RUTA_Y}) rotate(${-(rotate + GRID_ANGLE)}) scale(${1 / ZOOM})`}
                >
                  <rect
                    x={-13}
                    y={-8}
                    width={26}
                    height={16}
                    rx={3}
                    fill="var(--color-accent)"
                    stroke="#fff"
                    strokeWidth={1.5}
                  />
                  <text
                    y={4}
                    fontSize={9.5}
                    fontWeight="700"
                    textAnchor="middle"
                    fill="#fff"
                  >
                    259
                  </text>
                </g>
              ))}
            </g>

            {POIS.map((p) => (
              <g key={p.label} transform={upright(p.x, p.y)}>
                <circle r={5.5} fill={p.color} stroke="#fff" strokeWidth={2} />
                <text
                  x={10}
                  y={3.5}
                  fontSize={10}
                  fontWeight="600"
                  fill={p.color}
                >
                  {p.label}
                </text>
              </g>
            ))}
          </g>
        </svg>
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
