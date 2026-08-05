"use client";

import type { AppConfig, RoleSuggestion } from "@/lib/api";
import { CURATED_ROLES } from "@/lib/roles";
import { cx } from "../ui/cx";

function PanelLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="m-0 mb-2 text-[10.5px] font-bold tracking-[0.05em] text-slate-faint uppercase">
      {children}
    </h2>
  );
}

function ChoicePill({
  selected,
  dashed = false,
  grow = false,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  selected?: boolean;
  dashed?: boolean;
  grow?: boolean;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      className={cx(
        // min-h-11 (44px) is the touch-target floor — the old px-3.5/py-[7px]
        // pills measured ~30px tall, too small to tap reliably on a phone.
        "inline-flex min-h-11 items-center justify-center rounded-pill px-3.5 text-[12.5px] font-semibold transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong",
        grow && "flex-1 px-0",
        dashed ? "border border-dashed" : "border",
        selected
          ? "border-accent-strong bg-accent-strong text-white"
          : "border-line-plain bg-transparent text-ink hover:border-slate-faint",
      )}
      {...rest}
    />
  );
}

/**
 * The panel that floats over the workspace map: what we detected, how far to
 * look, and the one button that spends the search.
 *
 * "Start analysis" is `--pin`, not `--accent` — in the mockup the CTA matches
 * the map pin, which is what ties the panel to the place you chose.
 */
export default function StartPanel({
  config,
  suggestions,
  selected,
  radiusKm,
  radiusOptions,
  submitting,
  error,
  onToggleRole,
  onAddRole,
  onRadius,
  onStart,
}: {
  config: AppConfig | null;
  suggestions: RoleSuggestion[];
  selected: string[];
  radiusKm: number;
  radiusOptions: number[];
  submitting: boolean;
  error: string | null;
  onToggleRole: (label: string) => void;
  onAddRole: (label: string) => void;
  onRadius: (km: number) => void;
  onStart: () => void;
}) {
  const maxRoles = config?.max_roles ?? 1;
  const unpicked = CURATED_ROLES.filter(
    (r) => !suggestions.some((s) => s.label === r),
  );

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="m-0 text-[14.5px] font-bold text-ink">
          Ready when you are
        </h2>
        <p className="mt-[3px] mb-0 text-[12.5px] leading-normal text-slate-muted">
          {suggestions.length === 1
            ? "I found 1 role that matches what you told me."
            : `I found ${suggestions.length} roles that match what you told me.`}
        </p>
      </div>

      <div>
        <PanelLabel>Roles detected</PanelLabel>
        <div className="flex flex-wrap gap-2">
          {suggestions.map((s) => (
            <ChoicePill
              key={s.label}
              title={s.why}
              selected={selected.includes(s.label)}
              onClick={() => onToggleRole(s.label)}
            >
              {s.label.replace(/\b\w/g, (c) => c.toUpperCase())}
            </ChoicePill>
          ))}
        </div>
        <p className="mt-2 mb-0 text-[11.5px] text-slate-faint">
          {maxRoles === 1
            ? "One role per search on your current plan."
            : `Up to ${maxRoles} roles per search.`}
        </p>

        {unpicked.length > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-[11.5px] text-slate-muted">
              Or pick a common role
            </summary>
            <div className="mt-2 flex flex-wrap gap-2">
              {unpicked.map((role) => (
                <ChoicePill key={role} dashed onClick={() => onAddRole(role)}>
                  + {role}
                </ChoicePill>
              ))}
            </div>
          </details>
        )}
      </div>

      <div>
        <PanelLabel>Search radius</PanelLabel>
        <div className="flex gap-2">
          {radiusOptions.map((km) => (
            <ChoicePill
              key={km}
              grow
              selected={radiusKm === km}
              onClick={() => onRadius(km)}
            >
              {km} km
            </ChoicePill>
          ))}
        </div>
      </div>

      {error && (
        <p role="alert" className="m-0 text-[12.5px] text-pin">
          {error}
        </p>
      )}

      <button
        type="button"
        onClick={onStart}
        disabled={submitting || selected.length === 0}
        className="rounded-panel bg-pin px-4 py-3.5 text-sm font-bold text-white shadow-pin transition-opacity duration-150 hover:opacity-95 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-pin disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none"
      >
        {submitting ? "Starting analysis…" : "Start analysis"}
      </button>
    </div>
  );
}
