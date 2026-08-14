"use client";

import { useEffect, useRef, useState } from "react";

/**
 * The greeting, the one input and the quick-picks — mockup 2's centre column.
 *
 * Extracted so the full-screen first visit and the overlay a returning user
 * gets are literally the same control rather than two copies that drift.
 */
const QUICK_PICKS = [
  { label: "Line cook", text: "Line cook work" },
  { label: "Kitchen hand", text: "Kitchen hand work" },
  { label: "Barista", text: "Barista work in a cafe" },
  { label: "Retail assistant", text: "Retail assistant work in a shop" },
];

function SearchIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      aria-hidden="true"
      className="flex-none"
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

export default function AskBlock({
  firstName,
  busy,
  error,
  /**
   * Free search spent. Everything that would reach `POST /roles/interpret` is
   * turned off here — the LLM call is billed whether or not the search that
   * follows is allowed to run.
   */
  blockedReason,
  autoFocus = false,
  onSubmit,
}: {
  firstName: string | null;
  busy: boolean;
  error: string | null;
  blockedReason?: string | null;
  autoFocus?: boolean;
  onSubmit: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const blocked = Boolean(blockedReason);

  useEffect(() => {
    if (autoFocus && !blocked) inputRef.current?.focus();
  }, [autoFocus, blocked]);

  const submit = (value: string) => {
    const trimmed = value.trim();
    if (trimmed && !busy && !blocked) onSubmit(trimmed);
  };

  return (
    <div className="w-full max-w-[660px] text-center">
      <h1 className="m-0 mb-2.5 text-[26px] leading-tight font-semibold tracking-[-0.01em] text-ink sm:text-[30px]">
        {firstName ? `Hello ${firstName}` : "Hello"} — what role do you want
        next?
      </h1>
      <p className="m-0 mb-6 text-sm text-slate-muted sm:mb-[26px]">
        Tell me a little about your experience too, and I&apos;ll search the
        streets around you.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(text);
        }}
        className="flex items-center gap-3 rounded-pill border border-line-cool bg-surface-plain py-3 pr-3 pl-4 shadow-input sm:pl-[18px]"
      >
        <span className="text-slate-faint">
          <SearchIcon />
        </span>
        <label htmlFor="ask" className="sr-only">
          What kind of work are you looking for?
        </label>
        <input
          id="ask"
          ref={inputRef}
          type="text"
          value={text}
          disabled={blocked}
          onChange={(e) => setText(e.target.value)}
          placeholder={
            blocked
              ? "Your free search has been used"
              : "Ask me for a job — e.g. kitchen work near Surry Hills"
          }
          className="min-w-0 flex-1 border-0 bg-transparent text-[15px] text-ink placeholder:text-slate-faint focus:outline-none disabled:cursor-not-allowed"
        />
        <button
          type="submit"
          disabled={busy || blocked || !text.trim()}
          aria-label={busy ? "Thinking" : "Find me a job"}
          className="flex h-11 w-11 flex-none items-center justify-center rounded-full bg-accent-strong text-white transition-opacity duration-150 hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? (
            <span className="block h-4 w-4 animate-[spin_0.8s_linear_infinite] rounded-full border-2 border-white/40 border-t-white" />
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M12 19V5M5 12l7-7 7 7"
                stroke="currentColor"
                strokeWidth="2.2"
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </button>
      </form>

      <div className="mt-4 flex flex-wrap justify-center gap-2 sm:mt-[18px]">
        {QUICK_PICKS.map((p) => (
          <button
            key={p.label}
            type="button"
            disabled={busy || blocked}
            onClick={() => {
              setText(p.text);
              submit(p.text);
            }}
            className="inline-flex min-h-11 items-center justify-center rounded-pill border border-line-cool bg-white/90 px-3.5 text-[12.5px] font-medium text-slate-strong transition-colors duration-150 hover:border-line-plain hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong disabled:cursor-not-allowed disabled:opacity-50"
          >
            {p.label}
          </button>
        ))}
      </div>

      {(blockedReason || error) && (
        <p
          role={error ? "alert" : undefined}
          className="mx-auto mt-5 mb-0 max-w-[46ch] rounded-panel border border-line-cool bg-surface-plain px-4 py-2.5 text-[13px] text-pin"
        >
          {blockedReason || error}
        </p>
      )}
    </div>
  );
}
