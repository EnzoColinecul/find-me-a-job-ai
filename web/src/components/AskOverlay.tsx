"use client";

import { useEffect, useRef } from "react";
import type { Me } from "@/lib/api";
import AskBlock from "./AskBlock";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * The same question as `HomeScreen`, asked over the workspace instead of
 * instead of it.
 *
 * A returning user already has a map, a location and a history; sending them
 * back to a blank greeting throws all of that away and makes the app feel like
 * it forgot them. So the greeting floats, the workspace shows through blurred,
 * and dismissing it puts them back where they were.
 *
 * Dismissal needs somewhere to land, which is why `page.tsx` only reaches for
 * this once there's a prior search — on a genuinely first visit there is
 * nothing behind the overlay and the full-screen greeting is still right.
 */
export default function AskOverlay({
  me,
  busy,
  error,
  blockedReason,
  onSubmit,
  onDismiss,
}: {
  me: Me;
  busy: boolean;
  error: string | null;
  blockedReason?: string | null;
  onSubmit: (text: string) => void;
  onDismiss: () => void;
}) {
  const firstName = me.name ? me.name.split(" ")[0] : null;
  const panelRef = useRef<HTMLDivElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    returnTo.current = document.activeElement as HTMLElement | null;
    // Focus must not be able to wander into the workspace behind: it's visible
    // through the blur, so tabbing to something you can see but can't use is a
    // trap of its own.
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onDismiss();
        return;
      }
      if (e.key !== "Tab" || !panelRef.current) return;
      const nodes = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE),
      );
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || !panelRef.current.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      returnTo.current?.focus?.();
    };
  }, [onDismiss]);

  return (
    <div
      // The blur lives on the scrim, not on the workspace: filtering the map
      // container itself would blur it before compositing and drop the frame
      // rate on a live Google map, and it would blur this panel with it.
      className="fixed inset-0 z-40 flex items-center justify-center overflow-y-auto bg-paper/55 px-5 py-16 backdrop-blur-sm"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onDismiss();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="What role do you want next?"
        className="relative w-full max-w-[660px]"
      >
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Close and go back to your workspace"
          className="absolute -top-12 right-0 inline-flex h-11 w-11 items-center justify-center rounded-full border border-line-cool bg-surface-plain text-slate-muted shadow-card transition-colors duration-150 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M6 6l12 12M18 6L6 18"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
            />
          </svg>
        </button>

        <AskBlock
          firstName={firstName}
          busy={busy}
          error={error}
          blockedReason={blockedReason}
          autoFocus
          onSubmit={onSubmit}
        />
      </div>
    </div>
  );
}
