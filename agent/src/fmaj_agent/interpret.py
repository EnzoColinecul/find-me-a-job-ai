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

Respond with ONLY this JSON:
{{"roles": [{{"label": "...", "curated_key": "..." | null, "why": "short reason"}}]}}
"""


def interpret_roles(text: str) -> list[RoleSuggestion]:
    """Free text -> ordered role suggestions. Never raises; falls back to the raw text."""
    text = (text or "").strip()
    if not text:
        return []

    curated = "\n".join(f"- {r}" for r in mapping.curated_roles())
    prompt = _PROMPT.format(text=text[:1500], curated=curated,
                            max_suggestions=MAX_SUGGESTIONS)
    model = (config.GEMINI_MODEL if config.LLM_PROVIDER == "gemini"
             else config.TRIAGE_MODEL)
    try:
        turn = get_provider().complete(
            "", [{"role": "user", "text": prompt}],
            model=model, use_tools=False, max_tokens=600,
        )
        raw = turn.text
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
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
            return out
        logger.warning("interpretation produced no usable roles for %r", text[:80])
    except Exception:  # noqa: BLE001 — never block the user on interpretation
        logger.exception("role interpretation failed")

    # Fallback: treat their text as a single role (Text Search will handle it).
    return [RoleSuggestion(label=text[:60].lower(), curated_key=None,
                           why="Using your words as the search term.")]
