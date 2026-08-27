import type { Search, TraceStep } from "./api";

/**
 * Turn a trace step into the first-person sentence the panel shows.
 *
 * The panel's header promises "nothing hidden", which cuts both ways: the
 * sentence must be *readable*, but it must not assert anything the step doesn't
 * actually tell us. Three rules follow:
 *
 *  1. **Only use fields we have.** The design mockup says things like "Foveaux
 *     Coffee, 400 m from your pin" — we don't persist per-company coordinates
 *     (see the "Numbered result pins" card), so no sentence here mentions
 *     distance. Better a shorter true sentence than a padded invented one.
 *  2. **Describe the call, not a conclusion.** `web_search` means we searched,
 *     not that the company "has no website" — that's an inference the tool
 *     result doesn't support.
 *  3. **Match the tense to the search.** A finished search narrated in the
 *     present ("Searching the web for…") reads as though it is still running,
 *     which is exactly the kind of small lie this panel exists not to tell.
 *
 * Anything unrecognised falls back to a plain description rather than a guess.
 */

/**
 * Company names arrive from Places already correctly cased ("Marlowe's Kitchen"),
 * so they are used verbatim. An earlier version title-cased them and produced
 * "Marlowe'S Kitchen" — \b matches after an apostrophe.
 */
function subject(step: TraceStep): string {
  return step.text || "This place";
}

/** Reads as a noun phrase: "a line cook", "a chef or barista". */
function rolePhrase(search: Search): string {
  const roles = search.params.roles ?? [];
  if (roles.length === 0) return "the work you asked about";
  if (roles.length === 1) return `a ${roles[0]}`;
  return `a ${roles.slice(0, -1).join(", ")} or ${roles[roles.length - 1]}`;
}

function placePhrase(search: Search): string {
  const label = search.params.location_label;
  if (!label) return "the area you picked";
  // "Surry Hills NSW 2010" → "Surry Hills"
  return (
    label
      .split(",")[0]
      ?.trim()
      .replace(/\s+(NSW|VIC|QLD|WA|SA|TAS|NT|ACT)\s*\d{4}$/i, "") || label
  );
}

export function isLive(search: Search): boolean {
  return search.status === "pending" || search.status === "running";
}

/**
 * Human names for the tools, for the small source chip under each sentence.
 *
 * The panel used to print the raw identifier — `report`, `extract_contact`,
 * `web_search` — which is our vocabulary, not the user's. These are still the
 * real calls (nothing is invented or merged), just said in English. Keep this
 * honest: if a label ever stops naming the call it sits under, fix the label,
 * don't loosen the rule. The backend has the same constraint on `TOOL_LABELS`
 * in `agent/src/fmaj_agent/trace.py`.
 */
const TOOL_DISPLAY: Record<string, string> = {
  // Keep in step with `TOOL_LABELS` in `agent/src/fmaj_agent/trace.py` — the
  // values there are the keys here, and every one of them must be covered or
  // the fallback prints something like "seek company".
  "places.nearby": "Nearby places",
  triage: "Shortlist",
  fetch_page: "Their website",
  extract_jobs: "Their listings",
  "seek.company": "Seek employer page",
  web_search: "Web search",
  extract_contact: "Contact details",
  report: "Result",
};

export function toolLabel(tool: string): string {
  return TOOL_DISPLAY[tool] ?? tool.replace(/[._]/g, " ");
}

export function narrate(step: TraceStep, search: Search): string {
  const who = subject(step);
  const live = isLive(search);

  switch (step.tool) {
    case "places.nearby":
      return live
        ? `Scanning ${placePhrase(search)} within ${search.params.radius_km} km for places that hire ${rolePhrase(search)}.`
        : `Scanned ${placePhrase(search)} within ${search.params.radius_km} km for places that hire ${rolePhrase(search)}.`;

    case "triage":
      if (step.tag === "skipping") {
        // The meta carries the real reason (not a likely employer, or an error).
        if (step.meta.startsWith("error")) {
          return live
            ? `${who} — I hit a problem looking into this one, so I'm leaving it out.`
            : `${who} — I hit a problem looking into this one, so I left it out.`;
        }
        return live
          ? `${who} doesn't look like somewhere that hires ${rolePhrase(search)} — leaving it out.`
          : `${who} didn't look like somewhere that hires ${rolePhrase(search)} — left it out.`;
      }
      return live
        ? `${who} looks worth a proper look.`
        : `${who} looked worth a proper look.`;

    case "fetch_page":
      if (step.meta) {
        return live
          ? `${who} has a website — reading ${step.meta}.`
          : `${who} has a website — read ${step.meta}.`;
      }
      return live ? `Reading a page from ${who}.` : `Read a page from ${who}.`;

    case "extract_jobs":
      if (step.tag === "found") {
        return live
          ? `${who} has openings listed — picking out the ones that match.`
          : `${who} has openings listed — picked out the ones that match.`;
      }
      return live
        ? `Looking through ${who}'s listings for a match.`
        : `Looked through ${who}'s listings for a match.`;

    case "seek.company":
      // Counts the openings on the employer's own Seek page — it never reads
      // the listings themselves (see the robots.txt note in CLAUDE.md), so the
      // sentence must not imply that it did.
      if (step.tag === "found") {
        return live
          ? `${who} has a Seek employer page with openings on it.`
          : `${who} has a Seek employer page with openings on it.`;
      }
      return live
        ? `Checking whether ${who} has an employer page on Seek.`
        : `Checked whether ${who} has an employer page on Seek.`;

    case "web_search":
      if (step.tag === "found") {
        return live
          ? `Searched the web for ${who} and found something to follow up.`
          : `Searched the web for ${who} and found something to follow up.`;
      }
      if (step.tag === "skipping") {
        return live
          ? `I've used up the web searches budgeted for ${who}, so I'll go with what I have.`
          : `I used up the web searches budgeted for ${who}, so I went with what I had.`;
      }
      return live
        ? `Searching the web for ${who} job listings.`
        : `Searched the web for ${who} job listings.`;

    case "extract_contact":
      if (step.tag === "found") {
        return live
          ? `${who} publishes a contact address — picked it up.`
          : `${who} publishes a contact address — picked it up.`;
      }
      return live
        ? `Looking for a contact address on ${who}'s site.`
        : `Looked for a contact address on ${who}'s site.`;

    case "report":
      return step.tag === "found"
        ? `Done with ${who} — worth contacting.`
        : `Done with ${who} — nothing useful this time.`;

    default:
      // An unmapped tool is still a real call; describe it plainly.
      if (step.text) return live ? `Working on ${who}.` : `Worked on ${who}.`;
      return live ? "Working…" : "Worked on this search.";
  }
}

/** The one-line version for the card over the map. */
export function currentAction(search: Search): string | null {
  const steps = search.steps ?? [];
  const last = steps[steps.length - 1];
  return last ? narrate(last, search) : null;
}
