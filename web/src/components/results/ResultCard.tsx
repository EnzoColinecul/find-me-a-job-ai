"use client";

import { useState } from "react";
import type { SearchResult } from "@/lib/api";
import { classifyLinks, type LinkKind } from "@/lib/links";
import { cx } from "../ui/cx";

/** Live listings read as "found"; search pages and informal posts stay muted. */
const TONE: Record<LinkKind, string> = {
  live_listing: "border-success/40 bg-success/10 text-success-deep",
  careers_page: "border-accent/30 bg-accent/10 text-accent",
  company_profile: "border-accent/30 bg-accent/10 text-accent",
  board_search: "border-line-plain bg-paper-deep text-slate-muted",
  community_post: "border-line-plain bg-paper-deep text-slate-muted",
  other: "border-line-plain bg-paper-deep text-slate-muted",
};

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
      className="flex-none rounded-pill bg-paper-deep px-2.5 py-1 text-[10.5px] font-semibold text-ink transition-colors duration-150 hover:bg-line-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/**
 * One company in the results column (mockup 4).
 *
 * `index` numbers the card. The mockup also drops a matching numbered pin on
 * the map; that needs each company's coordinates, which the pipeline reads from
 * Places but doesn't persist — logged as a follow-up rather than faked here.
 */
export default function ResultCard({
  result,
  index,
  featured = false,
}: {
  result: SearchResult;
  index: number;
  featured?: boolean;
}) {
  const links = classifyLinks(result.links);

  return (
    <article
      className={cx(
        "rounded-panel border p-3.5",
        featured
          ? "border-accent/30 bg-accent/6"
          : "border-line-cool bg-surface-plain",
      )}
    >
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden="true"
          className={cx(
            "mt-px flex h-[19px] w-[19px] flex-none items-center justify-center rounded-full text-[11px] font-bold text-white",
            featured ? "bg-pin" : "bg-accent-strong",
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
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {links.map((l) => (
                <li key={l.url} className="flex flex-col gap-0.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span
                      className={cx(
                        "rounded-pill border px-1.5 py-px text-[10px] font-semibold",
                        TONE[l.kind],
                      )}
                    >
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
                    className="text-[11.5px] break-all"
                  >
                    {l.display}
                  </a>
                </li>
              ))}
            </ul>
          )}

          {result.emails.length > 0 && (
            <ul className="m-0 mt-2 flex list-none flex-col gap-1.5 p-0">
              {result.emails.map((m) => (
                <li key={m} className="flex items-center gap-2">
                  <code className="min-w-0 truncate font-mono text-[11.5px] text-ink">
                    {m}
                  </code>
                  <CopyButton value={m} />
                </li>
              ))}
            </ul>
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
