"""Does a live job title actually match the role the user asked for?

The bug this exists for: `find_seek_company_page` counted three vacancies at
Virtual IT Group, so the agent reported a `job_listing` for a "software
developer" search. None of the three were developer jobs. **Counting vacancies
proves a company is hiring; it does not prove it is hiring this person.**

Matching titles is a judgement call, not a keyword test. "Full Stack Engineer",
"Backend Developer" and "Software Engineer II" all match "software developer";
"Business Development Manager" does not, even though it contains the word
"development", and "IT Support Officer" does not either. No regex gets that
right, so the judge is the LLM — one cheap batched call per company, on the
triage model.

**Fails CLOSED.** If the model is unreachable, or its answer is unparseable, or
we could not read any titles, the verdict is "no match" — the same stance
`find_seek_company_page` already takes on unfamiliar markup. Surfacing an
unverified listing is precisely the bug being fixed; showing one fewer link is
not.

`config.ROLE_MATCH_THRESHOLD` (default 0.8) is the confidence the model must
express before a title counts. It is a knob on *this* judgement, not a measured
accuracy figure — `evals/golden.yaml` is what measures the latter.
"""
import json
import logging
import re
from dataclasses import dataclass, field

from fmaj_agent import config
from fmaj_agent.models import ToolResult
from fmaj_agent.providers import get_provider

logger = logging.getLogger(__name__)

#: Never send more than this many titles to the judge. An employer page with 40
#: vacancies is a big prompt for a decision that only needs one hit, and the
#: titles are ordered most-relevant-first by the boards themselves.
MAX_TITLES = 25

#: How many rejected titles to name in a refusal. Enough for the model (and the
#: trace) to see why, short enough not to flood the tool result.
MAX_NAMED = 5


@dataclass(frozen=True)
class TitleVerdict:
    """One title, judged against the roles sought."""

    title: str
    score: float = 0.0
    role: str = ""
    why: str = ""

    @property
    def matches(self) -> bool:
        return self.score >= config.ROLE_MATCH_THRESHOLD


@dataclass
class MatchReport:
    matched: list[TitleVerdict] = field(default_factory=list)
    rejected: list[TitleVerdict] = field(default_factory=list)
    #: False when we could not judge at all (no titles, or the model failed).
    #: Distinct from "judged and rejected" so the trace can tell them apart.
    judged: bool = True

    def __bool__(self) -> bool:
        return bool(self.matched)

    @property
    def titles(self) -> list[str]:
        return [v.title for v in self.matched]

    def refusal(self, roles: list[str]) -> str:
        """Why this source doesn't answer the search — written for the model."""
        wanted = " / ".join(roles) or "the role"
        if not self.judged:
            what = "check" if self.rejected else "read"
            return (
                f"could not {what} the vacancy titles against {wanted} — "
                "don't link to this as a listing"
            )
        named = ", ".join(f'"{v.title}"' for v in self.rejected[:MAX_NAMED])
        extra = len(self.rejected) - MAX_NAMED
        more = f" (+{extra} more)" if extra > 0 else ""
        return (
            f"{len(self.rejected)} vacancy title(s) here, none matching {wanted}: "
            f"{named}{more}. Do NOT report this as a job listing — keep looking "
            "(the company's own site, or a careers page / contact email)."
        )


# ── deterministic fast path ────────────────────────────────────────────────
# Cheap, offline, and only ever used to ACCEPT. There is no symmetric "obviously
# not a match" rule: that is where the interesting mistakes live, and it is
# exactly what we are paying the model to decide.

def _normalise(text: str) -> str:
    """Lowercase, drop bracketed asides and punctuation, collapse whitespace."""
    t = re.sub(r"[(\[{][^)\]}]*[)\]}]", " ", (text or "").lower())
    t = re.sub(r"[^a-z0-9+#]+", " ", t)
    return " ".join(t.split())


def _contains(haystack: str, needle: str) -> bool:
    """Whole-phrase containment, so "chef" doesn't match "kitchenchef"."""
    return bool(needle) and f" {needle} " in f" {haystack} "


def _obvious(title: str, roles: list[str]) -> str | None:
    """The role stated verbatim in the title -> match, no model call needed."""
    t = _normalise(title)
    for role in roles:
        if _contains(t, _normalise(role)):
            return role
    return None


# ── the judge ──────────────────────────────────────────────────────────────

_PROMPT = """\
A job seeker is looking for work as: {roles}

Below are the titles of live vacancies at ONE company. For each title, decide how
confident you are that the seeker would consider it a match — the same kind of
work, at a level they could plausibly apply for.

- Different wording for the same job IS a match: "Full Stack Engineer",
  "Backend Developer" and "Software Engineer II" all match "software developer".
- A different profession is NOT a match, even when it shares a word:
  "Business Development Manager" and "IT Support Officer" do not match
  "software developer"; "Kitchen Designer" does not match "kitchen hand".
- A far more senior title than the role names (e.g. "Head of Engineering" for
  "software developer") is a weak match — score it low.

Titles:
{titles}

Respond with ONLY this JSON, one entry per title, in the same order:
{{"verdicts": [{{"title": "...", "role": "<which sought role>" | null,
  "score": 0.0, "why": "<max 8 words>"}}]}}
"""

#: Judging the same titles twice inside one company run is free this way — the
#: Seek gate and the report-time check usually ask about the same list.
_cache: dict[tuple, MatchReport] = {}


def _parse(raw: str | None) -> list[dict] | None:
    """Tolerant JSON extraction — same shape as interpret._parse_json."""
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1]):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("verdicts"), list):
            return data["verdicts"]
    return None


def _judge(titles: list[str], roles: list[str]) -> list[TitleVerdict] | None:
    """One batched model call. None means "couldn't judge" — never "no match"."""
    prompt = _PROMPT.format(
        roles=", ".join(roles),
        titles="\n".join(f"- {t}" for t in titles),
    )
    model = (config.GEMINI_MODEL if config.LLM_PROVIDER == "gemini"
             else config.TRIAGE_MODEL)
    try:
        turn = get_provider().complete(
            "", [{"role": "user", "text": prompt}],
            model=model, use_tools=False,
            # Gemini 3 spends part of the budget on thinking tokens; too tight a
            # limit returns empty text and nothing to parse (see interpret.py).
            max_tokens=2048, json_mode=True, purpose="role_match",
        )
    except Exception:  # noqa: BLE001 — a flaky judge must not fail the company
        logger.warning("role match judge failed for %s", roles, exc_info=True)
        return None
    verdicts = _parse(turn.text)
    if verdicts is None:
        logger.warning("role match judge returned unparseable output: %r",
                       (turn.text or "")[:200])
        return None
    by_title = {t.lower(): t for t in titles}
    out: list[TitleVerdict] = []
    for item in verdicts:
        if not isinstance(item, dict):
            continue
        title = by_title.get(str(item.get("title", "")).strip().lower())
        if not title:
            continue  # a title we never sent — ignore rather than trust it
        try:
            score = float(item.get("score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        out.append(TitleVerdict(
            title=title,
            score=min(max(score, 0.0), 1.0),
            role=str(item.get("role") or ""),
            why=str(item.get("why", ""))[:80],
        ))
    return out or None


def match_titles(titles, roles) -> MatchReport:
    """Judge job titles against the roles sought. Never raises.

    Order is preserved and duplicates collapse, so a board that repeats a title
    doesn't get judged (or charged for) twice.
    """
    clean: list[str] = []
    seen: set[str] = set()
    for t in titles or []:
        t = " ".join(str(t or "").split())[:120]
        if t and t.lower() not in seen:
            seen.add(t.lower())
            clean.append(t)
    wanted = [r for r in (str(x or "").strip() for x in roles or []) if r]
    if not clean or not wanted:
        # No titles is "couldn't judge"; no roles is a caller bug, and in both
        # cases claiming a match would be inventing one.
        return MatchReport(judged=False)

    key = (tuple(clean), tuple(wanted), config.ROLE_MATCH_THRESHOLD)
    if key in _cache:
        return _cache[key]

    matched: list[TitleVerdict] = []
    undecided: list[str] = []
    for title in clean[:MAX_TITLES]:
        role = _obvious(title, wanted)
        if role:
            matched.append(TitleVerdict(title=title, score=1.0, role=role,
                                        why="role named in the title"))
        else:
            undecided.append(title)

    rejected: list[TitleVerdict] = []
    judged = True
    if undecided:
        verdicts = _judge(undecided, wanted)
        if verdicts is None:
            # Fail closed: unjudged titles are not matches. Anything the fast
            # path already accepted still stands — that needed no model.
            judged = bool(matched)
            rejected = [TitleVerdict(title=t, why="could not be judged")
                        for t in undecided]
        else:
            for v in verdicts:
                (matched if v.matches else rejected).append(v)
            missing = {t.lower() for t in undecided} - {v.title.lower() for v in verdicts}
            rejected += [TitleVerdict(title=t, why="not judged")
                         for t in undecided if t.lower() in missing]

    report = MatchReport(matched=matched, rejected=rejected, judged=judged)
    _cache[key] = report
    return report


# ── gating a tool's output ─────────────────────────────────────────────────

def gate_seek(result: ToolResult, roles: list[str]) -> tuple[ToolResult, MatchReport | None]:
    """Only return a Seek employer link when a vacancy there matches the role.

    This is the Virtual IT Group fix. The tool proves the employer page has live
    vacancies; this decides whether any of them is the job the user asked for.
    """
    if not result.ok:
        return result, None
    report = match_titles(result.data.get("job_titles") or [], roles)
    if not report.matched:
        return ToolResult(ok=False, reason=report.refusal(roles)), report
    data = dict(result.data)
    data["matching_titles"] = report.titles
    data["matching_count"] = len(report.matched)
    return ToolResult(ok=True, data=data), report


def gate_adzuna(result: ToolResult, roles: list[str]) -> tuple[ToolResult, MatchReport | None]:
    """Drop Adzuna hits whose title isn't the role — the board matches loosely."""
    if not result.ok:
        return result, None
    jobs = result.data.get("jobs") or []
    if not jobs:
        return result, None
    report = match_titles([j.get("title") for j in jobs], roles)
    if not report.matched:
        return ToolResult(ok=False, reason=report.refusal(roles)), report
    keep = {t.lower() for t in report.titles}
    data = dict(result.data)
    data["jobs"] = [j for j in jobs if str(j.get("title") or "").lower() in keep]
    data["dropped_off_role"] = len(jobs) - len(data["jobs"])
    return ToolResult(ok=True, data=data), report


#: Tool name -> gate. `web_search` is deliberately absent: it returns page
#: titles ("Software Developer Jobs in Melbourne | SEEK"), not vacancy titles,
#: so filtering on them would reject good links. Listings sourced from a web
#: search are verified at report time instead.
GATES = {
    "find_seek_company_page": gate_seek,
    "search_jobs_adzuna": gate_adzuna,
}


def observed_titles(name: str, result: ToolResult | None) -> list[str]:
    """Vacancy titles a tool put in front of the model, for the report gate.

    The point is provenance: a title the agent never saw cannot be the one it
    claims to have matched.
    """
    if result is None or not result.ok:
        return []
    data = result.data or {}
    if name == "find_seek_company_page":
        return list(data.get("job_titles") or [])
    if name == "search_jobs_adzuna":
        return [str(j.get("title") or "") for j in (data.get("jobs") or [])]
    if name == "web_search":
        return [str(r.get("title") or "") for r in (data.get("results") or [])]
    return []
