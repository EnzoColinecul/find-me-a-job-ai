/**
 * Classify and prettify result links.
 *
 * The problem this solves, observed in the first real search (chef · Surry Hills):
 * a card showed two bare Seek URLs with no way to tell that one was a company
 * profile and the other a Sydney-wide search that may not be this venue's role at
 * all. A user shouldn't have to click a link to find out what it is.
 *
 * Classification is by URL pattern, client-side. The more accurate option is for
 * the agent to return `{url, kind, label}` from `report_findings`, but that needs
 * a schema change and an eval re-run — worth revisiting if these patterns prove
 * unreliable in practice.
 */

import {
  Briefcase,
  Building2,
  Link as LinkIcon,
  ListChecks,
  MessagesSquare,
  Search,
  Target,
  type LucideIcon,
} from "lucide-react";

export type LinkKind =
  | "live_listing"
  | "employer_listings"
  | "careers_page"
  | "company_profile"
  | "board_search"
  | "community_post"
  | "other";

export interface ClassifiedLink {
  url: string;
  kind: LinkKind;
  /** Short label for the badge, e.g. "Live listing". */
  label: string;
  /** Extra caveat shown next to informal sources. */
  note?: string;
  /** Bare domain, no protocol, no `www.` — the link's secondary line. */
  host: string;
  /** Domain + trimmed path. Kept for anywhere a fuller reference is wanted. */
  display: string;
}

export const KIND_LABELS: Record<LinkKind, string> = {
  live_listing: "Live listing",
  employer_listings: "Employer listings",
  careers_page: "Careers page",
  company_profile: "Company profile",
  board_search: "Job board search",
  community_post: "Community post",
  other: "Link",
};

/**
 * One icon per link kind, from a single library (lucide-react) so sizing, stroke
 * weight, and colour stay consistent across every badge. Icons render at
 * `currentColor`, so they inherit the badge's token-driven text colour. Any
 * unrecognised link falls through to `other` → a generic link icon, never an
 * overclaimed one.
 */
export const KIND_ICONS: Record<LinkKind, LucideIcon> = {
  live_listing: Target,
  employer_listings: ListChecks,
  careers_page: Briefcase,
  company_profile: Building2,
  board_search: Search,
  community_post: MessagesSquare,
  other: LinkIcon,
};

/** Most useful first: something you can apply to, then the company's own page. */
const ORDER: LinkKind[] = [
  "live_listing",
  "employer_listings",
  "careers_page",
  "company_profile",
  "board_search",
  "community_post",
  "other",
];

function hostOf(url: string): { host: string; path: string } | null {
  try {
    const u = new URL(url);
    return { host: u.hostname.replace(/^www\./, ""), path: u.pathname };
  } catch {
    return null;
  }
}

function classifyKind(host: string, path: string): LinkKind {
  const p = path.toLowerCase();

  if (host.includes("facebook.") || host.includes("gumtree.")) {
    return "community_post";
  }
  if (host.includes("seek.com")) {
    if (p.startsWith("/companies/")) return "company_profile";
    // A real Seek vacancy is /job/<id>.
    if (/^\/job\/\d+/.test(p)) return "live_listing";
    // Employer-scoped listings: /<slug>-jobs/at-this-company is filtered to this
    // employer, so it's a trustworthy set of their vacancies — not a name search.
    if (/-jobs\/at-this-company\/?$/.test(p)) return "employer_listings";
    // Anything else with a "-jobs/" slug is a keyword search results page, which
    // may not be this venue's role at all — keep it a low-confidence board search.
    return "board_search";
  }
  if (host.includes("linkedin.")) {
    if (p.startsWith("/jobs/view/")) return "live_listing";
    if (p.startsWith("/company/")) return "company_profile";
    return "board_search";
  }
  if (host.includes("indeed.")) {
    if (p.startsWith("/cmp/")) return "company_profile";
    if (p.startsWith("/viewjob") || p.startsWith("/rc/clk"))
      return "live_listing";
    return "board_search";
  }
  if (host.includes("adzuna.")) {
    return /\/details\//.test(p) ? "live_listing" : "board_search";
  }
  if (host.includes("jora.") || host.includes("careerone.")) {
    return "board_search";
  }

  // A careers-ish path on a normal website is a careers page — on the company's
  // own domain or anyone else's. Deliberately conservative everywhere else: a
  // badge that overclaims ("Live listing" on a page that isn't one) is worse
  // than a generic one, because the whole point is that the user can trust it
  // without clicking.
  if (/careers?|jobs|vacanc|work-with-us|employment|join-us|hiring/.test(p)) {
    return "careers_page";
  }
  return "other";
}

/** Strip protocol and query string; keep enough path to be recognisable. */
function display(host: string, path: string): string {
  const clean = path.replace(/\/$/, "");
  const full = `${host}${clean}`;
  if (full.length <= 52) return full;
  const segments = clean.split("/").filter(Boolean);
  const tail = segments[segments.length - 1] ?? "";
  const shortTail = tail.length > 28 ? `${tail.slice(0, 27)}…` : tail;
  return `${host}/…/${shortTail}`;
}

export function classifyLink(url: string): ClassifiedLink {
  const parsed = hostOf(url);
  if (!parsed) {
    return {
      url,
      kind: "other",
      label: KIND_LABELS.other,
      host: url,
      display: url,
    };
  }
  const kind = classifyKind(parsed.host, parsed.path);
  return {
    url,
    kind,
    label: KIND_LABELS[kind],
    note: kind === "community_post" ? "Informal — may expire" : undefined,
    host: parsed.host,
    display: display(parsed.host, parsed.path),
  };
}

export function classifyLinks(urls: string[]): ClassifiedLink[] {
  return urls
    .map((u) => classifyLink(u))
    .sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
}

/**
 * A URL in prose, plus the connector that introduces it ("… found at <url>")
 * and any brackets around it. Deliberately greedy to the end of the token, then
 * backed off one character so a sentence-ending "." isn't eaten as part of the
 * path.
 */
const URL_IN_PROSE =
  /(?:\s*[:;,\u2014\u2013-])?(?:\s+(?:at|on|via|see|from|here|link:?))?\s*[([]?\s*(?:https?:\/\/|www\.)[^\s\])]*[^\s\]).,;:!?]\s*[)\]]?/gi;

/**
 * Remove URLs from the agent's evidence sentence.
 *
 * Every link is already rendered above the evidence as a labelled link, so
 * repeating the raw URL inside the prose — percent-encoding and all — was noise,
 * and the longest, least readable line in the column. What's left is the
 * sentence: what was found, and why it's worth your time.
 *
 * The tidy-up passes exist because removing a URL leaves punctuation behind:
 * "…a chef vacancy: <url>." would otherwise end ":.", and "<url> and <url>."
 * would end "— and.". Returns "" when the evidence was nothing but a link —
 * callers should treat that as no evidence.
 *
 * A bare hostname with no scheme and no `www.` ("au.seek.com/x-jobs") is left
 * alone on purpose: the pattern that would catch it also eats email addresses
 * and ordinary prose, and a stray hostname is far less ugly than a swallowed
 * "info@boxtech.com.au".
 */
export function withoutUrls(text: string): string {
  return text
    .replace(URL_IN_PROSE, " ")
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/\s+(and|or)\s*(?=[.,;:]|$)/gi, "")
    .replace(/[:;,—–-]+(?=\s*[.!?])/g, "")
    .replace(/[\s,;:—–-]+$/, "")
    .replace(/^[\s,.;:—–-]+/, "")
    .trim();
}
