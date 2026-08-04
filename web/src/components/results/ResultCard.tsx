"use client";

import { useState } from "react";
import type { SearchResult } from "@/lib/api";
import { classifyLinks, type LinkKind } from "@/lib/links";
import { Card, TagChip, type TagTone } from "@/components/ui";

/** Live listings read as "found"; search pages and informal posts stay muted. */
const TONES: Record<LinkKind, TagTone> = {
  live_listing: "found",
  careers_page: "info",
  company_profile: "info",
  board_search: "muted",
  community_post: "muted",
  other: "muted",
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
          // Clipboard can be blocked (insecure context, permissions). Say so
          // rather than silently pretending the copy worked.
          setCopied(false);
        }
      }}
      className="rounded-pill border border-line-plain px-2.5 py-1 text-[12px] font-semibold text-slate-muted transition-colors duration-150 hover:border-line hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export default function ResultCard({ result }: { result: SearchResult }) {
  const links = classifyLinks(result.links);

  return (
    <Card className="px-4 py-4">
      <h3 className="m-0 text-[15px] font-bold text-ink">{result.company}</h3>
      {result.address && (
        <p className="mt-0.5 mb-0 text-[13px] text-slate-muted">
          {result.address}
        </p>
      )}

      {links.length > 0 && (
        <ul className="mt-3 grid list-none gap-2 p-0">
          {links.map((l) => (
            <li key={l.url} className="grid gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <TagChip tone={TONES[l.kind]}>{l.label}</TagChip>
                {l.note && (
                  <span className="text-[11px] text-slate-muted">{l.note}</span>
                )}
              </div>
              <a
                href={l.url}
                target="_blank"
                rel="noreferrer noopener"
                title={l.url}
                className="truncate text-[13px]"
              >
                {l.display}
              </a>
            </li>
          ))}
        </ul>
      )}

      {result.emails.length > 0 && (
        <ul className="mt-3 grid list-none gap-2 p-0">
          {result.emails.map((m) => (
            <li key={m} className="flex flex-wrap items-center gap-2">
              <TagChip tone="info">✉️ Contact</TagChip>
              <code className="rounded-tag bg-paper-deep px-1.5 py-0.5 text-[13px] text-ink">
                {m}
              </code>
              <CopyButton value={m} />
            </li>
          ))}
        </ul>
      )}

      {result.evidence && (
        <p className="mt-3 mb-0 border-t border-line-soft pt-2.5 text-[12px] leading-normal text-slate-muted">
          {result.evidence}
        </p>
      )}
    </Card>
  );
}
