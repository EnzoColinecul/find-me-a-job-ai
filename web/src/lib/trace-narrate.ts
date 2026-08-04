import type { Search, TraceStep } from "./api";

/**
 * Turn a trace step into the first-person sentence the panel shows.
 *
 * The panel's header promises "nothing hidden", which cuts both ways: the
 * sentence must be *readable*, but it must not assert anything the step doesn't
 * actually tell us. Two rules follow:
 *
 *  1. **Only use fields we have.** The design mockup says things like "Foveaux
 *     Coffee, 400 m from your pin" — we don't persist per-company coordinates
 *     (see the "Numbered result pins" card), so no sentence here mentions
 *     distance. Better a shorter true sentence than a padded invented one.
 *  2. **Describe the call, not a conclusion.** `web_search` means we searched,
 *     not that the company "has no website" — that's an inference the tool
 *     result doesn't support.
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

export function narrate(step: TraceStep, search: Search): string {
  const who = subject(step);

  switch (step.tool) {
    case "places.nearby":
      return `Scanning ${placePhrase(search)} within ${search.params.radius_km} km for places that hire ${rolePhrase(search)}.`;

    case "triage":
      if (step.tag === "skipping") {
        // The meta carries the real reason (not a likely employer, or an error).
        return step.meta.startsWith("error")
          ? `${who} — I hit a problem looking into this one, so I'm leaving it out.`
          : `${who} doesn't look like somewhere that hires ${rolePhrase(search)} — leaving it out.`;
      }
      return `${who} looks worth a proper look.`;

    case "fetch_page":
      return step.meta
        ? `${who} has a website — reading ${step.meta}.`
        : `Reading a page from ${who}.`;

    case "extract_jobs":
      return step.tag === "found"
        ? `${who} has openings listed — picking out the ones that match.`
        : `Looking through ${who}'s listings for a match.`;

    case "web_search":
      return step.tag === "found"
        ? `Searched the web for ${who} and found something to follow up.`
        : step.tag === "skipping"
          ? `I've used up the web searches budgeted for ${who}, so I'll go with what I have.`
          : `Searching the web for ${who} job listings.`;

    case "extract_contact":
      return step.tag === "found"
        ? `${who} publishes a contact address — picked it up.`
        : `Looking for a contact address on ${who}'s site.`;

    case "report":
      return step.tag === "found"
        ? `Done with ${who} — worth contacting.`
        : `Done with ${who} — nothing useful this time.`;

    default:
      // An unmapped tool is still a real call; describe it plainly.
      return step.text ? `Working on ${who}.` : "Working…";
  }
}

/** The one-line version for the card over the map. */
export function currentAction(search: Search): string | null {
  const steps = search.steps ?? [];
  const last = steps[steps.length - 1];
  return last ? narrate(last, search) : null;
}
