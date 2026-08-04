"use client";

import { useState } from "react";
import StreetMapBackdrop from "./StreetMapBackdrop";
import { Card, Pill } from "./ui";

/**
 * Mockup 2 — the conversational opening. One question, one input, four ways in.
 *
 * The four quick-picks replace the old 16-role <details> list: the full curated
 * set is still one tap away inside the workspace, but the first screen shouldn't
 * open with a wall of job titles.
 */
const QUICK_PICKS = [
  { label: "Line cook", text: "Line cook work" },
  { label: "Kitchen hand", text: "Kitchen hand work" },
  { label: "Barista", text: "Barista work in a cafe" },
  { label: "Retail assistant", text: "Retail assistant work in a shop" },
];

export default function HomeScreen({
  firstName,
  busy,
  error,
  onSubmit,
}: {
  firstName: string | null;
  busy: boolean;
  error: string | null;
  onSubmit: (text: string) => void;
}) {
  const [text, setText] = useState("");

  const submit = (value: string) => {
    const trimmed = value.trim();
    if (trimmed && !busy) onSubmit(trimmed);
  };

  return (
    <main className="relative flex min-h-dvh items-center justify-center overflow-hidden px-5 py-12">
      <StreetMapBackdrop />

      <Card
        tone="plain"
        elevated
        className="relative w-full max-w-[560px] px-7 py-9 sm:px-10 sm:py-11"
      >
        <h1 className="m-0 mb-2 text-[22px] leading-tight font-extrabold text-ink sm:text-2xl">
          {firstName ? `Hello ${firstName}` : "Hello"} — what role do you want
          next?
        </h1>
        <p className="m-0 mb-6 text-sm leading-normal text-slate-muted">
          Tell me a little about your experience too, and I&apos;ll search the
          streets around you.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit(text);
          }}
        >
          <label htmlFor="ask" className="sr-only">
            What kind of work are you looking for?
          </label>
          <textarea
            id="ask"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              // Enter submits, Shift+Enter adds a line — the input is a textarea
              // because people write a sentence, not a job title.
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(text);
              }
            }}
            rows={3}
            placeholder="Ask me for a job — e.g. kitchen work near Surry Hills"
            className="w-full resize-none rounded-panel border border-line bg-surface px-4 py-3.5 text-[15px] leading-normal text-ink placeholder:text-slate-muted focus-visible:border-accent-strong focus-visible:outline-none"
          />

          <div className="mt-3 flex flex-wrap items-center gap-2">
            {QUICK_PICKS.map((p) => (
              <Pill
                key={p.label}
                onClick={() => {
                  setText(p.text);
                  submit(p.text);
                }}
                disabled={busy}
              >
                {p.label}
              </Pill>
            ))}
          </div>

          <button
            type="submit"
            disabled={busy || !text.trim()}
            className="mt-6 w-full rounded-panel border border-accent bg-accent px-6 py-3.5 text-[15px] font-semibold text-white transition-colors duration-150 hover:bg-accent-strong hover:border-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Thinking…" : "Find me a job"}
          </button>
        </form>

        {error && (
          <p role="alert" className="mt-4 mb-0 text-[13px] text-pin">
            {error}
          </p>
        )}
      </Card>
    </main>
  );
}
