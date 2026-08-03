"""Interpret a user's free-text description into concrete job roles to search.

The user says e.g. "I want to work in a restaurant, I've done some kitchen work"
and we propose ["kitchen hand", "chef", "dishwasher"] for them to confirm/edit.

Each suggestion carries `curated_key`: the role in role_mapping.yaml whose Places
types we borrow. That keeps discovery quality high even for labels we've never seen
(e.g. "dishwasher" -> borrows "kitchen hand" venue types instead of Text-Searching
"dishwasher", which would return appliance stores).
"""
import json
import logging
from dataclasses import dataclass

from fmaj_agent import config, mapping
from fmaj_agent.models import RoleSuggestion
from fmaj_agent.providers import get_provider

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 6

_PROMPT = """\
A job seeker described what they're looking for. Propose concrete job roles to search
for near them.

Their description:
\"\"\"{text}\"\"\"

Known roles (their venue types are already tuned — prefer these labels when they fit):
{curated}

Rules:
- Propose 1-{max_suggestions} roles, most relevant first.
- Prefer a known role label when it genuinely matches.
- You may propose a role that is not in the list (e.g. "dishwasher", "pastry chef").
  For those, set "curated_key" to the known role with the MOST SIMILAR workplaces,
  so we search the right kinds of venues. Use null only if nothing is close.
- Only propose roles the person could plausibly do based on what they said.
  Do not invent seniority or skills they never mentioned.
- Keep labels short, lowercase, and in the language of the description.
- If the description is too vague to name any concrete job role (e.g. "I need a job",
  "anything", "help me"), return an EMPTY roles array. Do not guess.

Respond with ONLY this JSON:
{{"roles": [{{"label": "...", "curated_key": "..." | null, "why": "short reason"}}]}}
"""

VAGUE_MESSAGE = (
    "We couldn't work out specific job roles from that. Try naming the kind of work "
    "or workplace — for example \"kitchen work in cafes\" or \"driving deliveries\"."
)
ERROR_MESSAGE = (
    "We couldn't process that just now. Please try again in a moment."
)


@dataclass
class Interpretation:
    """Result of interpreting free text.

    `ok=False` means we have nothing usable to search — the caller must show `message`
    and ask the user to rephrase. We deliberately do NOT fall back to searching their
    raw sentence: "i want to work as a software developer in my next role" is not a
    role and would produce a meaningless search.
    """

    roles: list[RoleSuggestion]
    ok: bool = True
    message: str = ""


def _parse_json(raw: str | None) -> dict | None:
    """Tolerant JSON extraction: handles ```json fences, prose wrappers, empty text."""
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    if text.startswith("```"):  # strip markdown fence
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def interpret_roles(text: str) -> Interpretation:
    """Free text -> ordered role suggestions. Never raises."""
    text = (text or "").strip()
    if not text:
        return Interpretation(roles=[], ok=False, message=VAGUE_MESSAGE)

    curated = "\n".join(f"- {r}" for r in mapping.curated_roles())
    prompt = _PROMPT.format(text=text[:1500], curated=curated,
                            max_suggestions=MAX_SUGGESTIONS)
    model = (config.GEMINI_MODEL if config.LLM_PROVIDER == "gemini"
             else config.TRIAGE_MODEL)
    try:
        turn = get_provider().complete(
            "", [{"role": "user", "text": prompt}],
            model=model, use_tools=False,
            # Gemini 3 spends part of the budget on thinking tokens — too small a
            # limit returns empty text and nothing to parse.
            max_tokens=2048, json_mode=True,
        )
        data = _parse_json(turn.text)
        if data is None:
            logger.warning("interpretation returned unparseable output: %r",
                           (turn.text or "")[:200])
            return Interpretation(roles=[], ok=False, message=ERROR_MESSAGE)
        out: list[RoleSuggestion] = []
        seen: set[str] = set()
        for item in data.get("roles", [])[:MAX_SUGGESTIONS]:
            label = str(item.get("label", "")).strip().lower()
            if not label or label in seen:
                continue
            seen.add(label)
            key = item.get("curated_key")
            key = str(key).strip().lower() if key else None
            if key and not mapping.resolve(key).curated:
                key = None  # model hallucinated a key that isn't in the mapping
            out.append(RoleSuggestion(label=label, curated_key=key,
                                      why=str(item.get("why", ""))[:140]))
        if out:
            return Interpretation(roles=out)
        logger.info("input too vague to interpret: %r", text[:80])
        return Interpretation(roles=[], ok=False, message=VAGUE_MESSAGE)
    except Exception:  # noqa: BLE001 — never block the user on interpretation
        logger.exception("role interpretation failed")
        return Interpretation(roles=[], ok=False, message=ERROR_MESSAGE)
