"use client";

/** The white bar floating at the top of the map, on both shell screens. */
export function MapBar({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2.5 rounded-panel border border-line-cool bg-surface-plain px-3.5 py-2.5 shadow-bar">
      {children}
    </div>
  );
}

export function SearchGlyph() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      aria-hidden="true"
      className="flex-none text-slate-muted"
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
  );
}

/** The pill that reports search progress, bottom-left of the map (mockup 4). */
export function StatusPill({
  tone,
  children,
}: {
  tone: "working" | "done" | "failed";
  children: React.ReactNode;
}) {
  const dot =
    tone === "done"
      ? "bg-success"
      : tone === "failed"
        ? "bg-pin"
        : "bg-warn animate-[pulse_1.6s_ease-in-out_infinite]";

  return (
    <div className="absolute bottom-5 left-5 flex max-w-[calc(100%-2.5rem)] items-center gap-2.5 rounded-pill bg-surface-plain py-2.5 pr-4 pl-3 shadow-bar">
      <span className={`h-2 w-2 flex-none rounded-full ${dot}`} />
      <span
        aria-live="polite"
        className="truncate text-[13px] font-semibold text-ink"
      >
        {children}
      </span>
    </div>
  );
}
