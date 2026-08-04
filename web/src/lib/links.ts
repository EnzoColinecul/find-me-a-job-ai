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

export type LinkKind =
  | "live_listing"
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
  /** What we actually render: domain + path, no protocol, no query string. */
  display: string;
}

export const KIND_LABELS: Record<LinkKind, string> = {
  live_listing: "🎯 Live listing",
  careers_page: "💼 Careers page",
  company_profile: "🏢 Company profile",
  board_search: "🔎 Job board search",
  community_post: "💬 Community post",
  other: "🔗 Link",
};

/** Most useful first: something you can apply to, then the company's own page. */
const ORDER: LinkKind[] = [
  "live_listing",
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
    // A real Seek vacancy is /job/<id>; anything else with a "-jobs/" slug is a
    // search results page, which may not be this venue's role at all.
    if (/^\/job\/\d+/.test(p)) return "live_listing";
    return "board_search";
  }
  if (host.includes("linkedin.")) {
    if (p.startsWith("/jobs/view/")) return "live_listing";
    if (p.startsWith("/company/")) return "company_profile";
    return "board_search";
  }
  if (host.includes("indeed.")) {
    if (p.startsWith("/cmp/")) return "company_profile";
    if (p.startsWith("/viewjob") || p.startsWith("/rc/clk")) return "live_listing";
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
    return { url, kind: "other", label: KIND_LABELS.other, display: url };
  }
  const kind = classifyKind(parsed.host, parsed.path);
  return {
    url,
    kind,
    label: KIND_LABELS[kind],
    note:
      kind === "community_post"
        ? "Informal — may expire"
        : kind === "board_search"
          ? "A search page, not a specific vacancy"
          : undefined,
    display: display(parsed.host, parsed.path),
  };
}

export function classifyLinks(urls: string[]): ClassifiedLink[] {
  return urls
    .map((u) => classifyLink(u))
    .sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
}
