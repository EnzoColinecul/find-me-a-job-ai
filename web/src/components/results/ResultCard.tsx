"use client";

import type { SearchResult } from "@/lib/api";
import { classifyLinks, KIND_ICONS, withoutUrls } from "@/lib/links";
import { Check, Copy, Mail } from "lucide-react";
import { useState } from "react";
import { cx } from "../ui/cx";

/**
 * Copies one value and says so.
 *
 * Two things it must not go back to being: an icon-only button with no
 * accessible name (a screen reader announced ten bare "button"s on this route),
 * and a 32x24 hit area. The label names *what* is copied, so ten of them on a
 * page are ten different controls rather than ten identical ones.
 */
function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <>
      <button
        type="button"
        aria-label={copied ? `Copied ${label}` : `Copy ${label}`}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1800);
          } catch {
            // Clipboard can be blocked (insecure context, permissions). Say
            // nothing rather than pretend the copy worked.
            setCopied(false);
          }
        }}
        className="inline-flex h-11 w-11 flex-none items-center justify-center rounded-2xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
      >
        {/* 44x44 hit area, small visual chip — same pattern as the sidebar
            toggle in `WorkspaceShell`. */}
        <span
          className={cx(
            "inline-flex h-6 items-center rounded-2xl bg-paper-deep px-2.5 text-[11px] font-semibold transition-colors duration-150",
            copied ? "text-success-deep" : "text-ink",
          )}
        >
          {copied ? (
            <Check aria-hidden="true" className="h-3 w-3 flex-none" />
          ) : (
            <Copy aria-hidden="true" className="h-3 w-3 flex-none" />
          )}
        </span>
      </button>
      {/* Confirmation for anyone who can't see the icon swap. Polite, and only
          populated on success, so it never announces a copy that didn't
          happen. */}
      <span role="status" aria-live="polite" className="sr-only">
        {copied ? `${label} copied` : ""}
      </span>
    </>
  );
}

/**
 * One company in the results column (mockup 4).
 *
 * `index` numbers the card and the matching numbered pin on the map. The two
 * are derived from the same ordered list (see `orderedResults`) so they always
 * agree; hovering the card highlights its pin via `onHover`.
 */
export default function ResultCard({
  result,
  index,
  onHover,
}: {
  result: SearchResult;
  index: number;
  /** Reports this card's place_id on hover/focus (null on leave) so the map can
   * highlight its pin. */
  onHover?: (placeId: string | null) => void;
}) {
  const links = classifyLinks(result.links);
  // The links are already on the card, labelled. Evidence that was only a URL
  // has nothing left to say once it's stripped, so the paragraph goes too.
  const evidence = withoutUrls(result.evidence ?? "");

  return (
    <article
      onMouseEnter={() => onHover?.(result.place_id)}
      onMouseLeave={() => onHover?.(null)}
      onFocus={() => onHover?.(result.place_id)}
      onBlur={() => onHover?.(null)}
      className={cx(
        "rounded-panel border p-3.5 transition-all duration-150",
        "border-line-cool bg-surface-plain",
        "hover:border-accent/40 hover:shadow-card focus-within:border-accent/40",
      )}
    >
      <div className="flex items-start gap-2.5">
        {/* Same size as the map pin it corresponds to — one token, one size. */}
        <span
          aria-hidden="true"
          className={cx(
            "mt-px flex h-6 w-6 flex-none items-center justify-center rounded-full text-[12px] font-bold text-white",
            "bg-accent-strong",
          )}
        >
          {index}
        </span>

        <div className="min-w-0 flex-1">
          <h3 className="m-0 text-[15px] font-bold text-ink">
            {result.company}
          </h3>
          {result.address && (
            <p className="mt-[3px] mb-2 text-[12px] leading-[1.45] text-slate-muted">
              {result.address}
            </p>
          )}

          {links.length > 0 && (
            <ul className="m-0 flex list-none flex-col gap-0.5 border-t border-line-cool p-0 pt-1.5">
              {links.map((l) => {
                const Icon = KIND_ICONS[l.kind];
                return (
                  <li key={l.url}>
                    {/*
                     * One 44px-tall target for the whole two-line block, rather
                     * than a 21px line of text: the kind, then where it goes.
                     *
                     * The link used to render the raw URL with `break-all`,
                     * which chopped percent-encoded paths mid-word
                     * ("junior-software-develo per-%…") — unreadable, and no
                     * more informative than the kind already is. The domain is
                     * the part a user actually judges the link by, so that is
                     * what's kept; the full URL stays in `title`.
                     */}
                    <a
                      href={l.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      title={l.url}
                      className="flex min-h-11 flex-col justify-center gap-0.5 rounded-card py-1 no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
                    >
                      <span className="flex items-center gap-1.5 text-[13px] font-semibold text-accent-strong">
                        <Icon
                          aria-hidden="true"
                          strokeWidth={2}
                          className="h-3.5 w-3.5 flex-none"
                        />
                        <span className="truncate">{l.label}</span>
                      </span>
                      {/* The domain is how a user decides whether to trust the link,
                          so it sits at body size — 11px is for labels only. */}
                      <span className="flex flex-wrap items-baseline gap-1.5 text-[12px] text-slate-muted">
                        <span className="truncate">{l.host}</span>
                        {l.note && <span>· {l.note}</span>}
                      </span>
                    </a>
                  </li>
                );
              })}
            </ul>
          )}

          {result.emails.length > 0 && (
            <div className="mt-2 flex flex-col gap-1">
              <span className="inline-flex items-center gap-1 py-px text-[11px] font-semibold text-ink">
                <Mail
                  aria-hidden="true"
                  strokeWidth={2}
                  className="h-3 w-3 flex-none"
                />
                Contact email
              </span>
              <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
                {result.emails.map((m) => (
                  <li key={m} className="flex items-center gap-1">
                    <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
                      {m}
                    </span>
                    <CopyButton value={m} label={`${m} for ${result.company}`} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          {evidence && (
            <p className="mt-2.5 mb-0 border-t border-line-cool pt-2 text-[12px] leading-normal text-slate-muted">
              {evidence}
            </p>
          )}
        </div>
      </div>
    </article>
  );
}
