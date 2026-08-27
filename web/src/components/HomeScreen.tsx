"use client";

import type { Me } from "@/lib/api";
import { logout } from "@/lib/auth";
import AppMark from "./AppMark";
import AskBlock from "./AskBlock";
import Avatar from "./Avatar";
import StreetMapBackdrop from "./StreetMapBackdrop";

/**
 * Mockup 2 — the first screen after signing in. One question, one input.
 *
 * Full-bleed map with the greeting sitting directly on it: no card. The map is
 * the hero on every screen, and wrapping this in a panel is what made the first
 * attempt look like a generic dialog.
 *
 * **First visit only.** Once the user has a search behind them the same
 * question is asked as an overlay over their real workspace (`AskOverlay`), so
 * returning doesn't throw away the map and location they already have. This
 * screen stays for the case where there's genuinely nothing to show underneath.
 */
export default function HomeScreen({
  me,
  busy,
  error,
  blockedReason,
  onSubmit,
}: {
  me: Me;
  busy: boolean;
  error: string | null;
  blockedReason?: string | null;
  onSubmit: (text: string) => void;
}) {
  const firstName = me.name ? me.name.split(" ")[0] : null;

  return (
    <main className="relative min-h-dvh overflow-hidden">
      <StreetMapBackdrop
        rotate={-4}
        spread={40}
        duration={26}
        blur={3}
        wash="strong"
      />

      <AppMark className="absolute top-5 left-5 sm:left-6" />
      <div className="absolute top-4 right-5 flex items-center gap-2 sm:right-6">
        <button
          type="button"
          onClick={() => logout()}
          className="inline-flex min-h-11 items-center rounded-pill px-2.5 py-1 text-[12px] font-medium text-slate-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
        >
          Sign out
        </button>
        <Avatar me={me} />
      </div>

      <div className="relative flex min-h-dvh items-center justify-center px-5 py-24">
        <AskBlock
          firstName={firstName}
          busy={busy}
          error={error}
          blockedReason={blockedReason}
          onSubmit={onSubmit}
        />
      </div>
    </main>
  );
}
