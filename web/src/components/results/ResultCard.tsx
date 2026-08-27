"use client";

import type { SearchResult } from "@/lib/api";
import { classifyLinks, KIND_ICONS } from "@/lib/links";
import { Check, Copy, Mail } from "lucide-react";
import { useState } from "react";
import { cx } from "../ui/cx";

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      type="button"
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
      className="inline-flex min-h-6 flex-none items-center rounded-2xl bg-paper-deep px-2.5 text-[10.5px] font-semibold text-ink transition-colors duration-150 hover:bg-line-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
    >
      {copied ? (
        <Check className="h-3 w-3 flex-none" />
      ) : (
        <Copy className="h-3 w-3 flex-none" />
      )}
    </button>
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
        <span
          aria-hidden="true"
          className={cx(
            "mt-px flex h-[19px] w-[19px] flex-none items-center justify-center rounded-full text-[11px] font-bold text-white",
            "bg-accent-strong",
          )}
        >
          {index}
        </span>

        <div className="min-w-0 flex-1">
          <h3 className="m-0 text-[13.5px] font-bold text-ink">
            {result.company}
          </h3>
          {result.address && (
            <p className="mt-[3px] mb-2 text-[11.5px] leading-[1.45] text-slate-muted">
              {result.address}
            </p>
          )}

          {links.length > 0 && (
            <ul className="m-0 flex list-none flex-col border-t border-line-cool pt-2 gap-2 p-0">
              {links.map((l) => {
                const Icon = KIND_ICONS[l.kind];
                return (
                  <li key={l.url} className="flex flex-col gap-0.5">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span
                        className={cx(
                          "inline-flex items-center gap-1 rounded-pill py-px text-[10px] font-semibold",
                        )}
                      >
                        <Icon
                          aria-hidden="true"
                          strokeWidth={2}
                          className="h-3 w-3 flex-none"
                        />
                        {l.label}
                      </span>
                      {l.note && (
                        <span className="text-[10px] text-slate-faint">
                          {l.note}
                        </span>
                      )}
                    </div>
                    <a
                      href={l.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      title={l.url}
                      className="text-[11.5px] break-all text-accent-strong"
                    >
                      {l.display}
                    </a>
                  </li>
                );
              })}
            </ul>
          )}

          {result.emails.length > 0 && (
            <div className="mt-2 flex flex-col gap-1">
              <span className="inline-flex items-center gap-1 py-px text-[10px] font-semibold">
                <Mail
                  aria-hidden="true"
                  strokeWidth={2}
                  className="h-3 w-3 flex-none"
                />
                Contact email
              </span>
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {result.emails.map((m) => (
                  <li key={m} className="flex items-center gap-2">
                    <span className="text-[11.5px] text-ink">{m}</span>
                    <CopyButton value={m} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          {result.evidence && (
            <p className="mt-2.5 mb-0 border-t border-line-cool pt-2 text-[11px] leading-normal text-slate-muted">
              {result.evidence}
            </p>
          )}
        </div>
      </div>
    </article>
  );
}
