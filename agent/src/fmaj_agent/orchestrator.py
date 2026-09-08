"""Per-company agent — provider-agnostic Bedrock/Gemini tool-use loop.

Flow (docs/PLAN.md §4):
  1. Triage: is this a plausible employer for the role? If not -> none (cheap).
  2. Tool loop: the model calls fetch_url / find_careers_link / search_jobs_adzuna /
     web_search / extract_emails, then report_findings.
  3. HARD BUDGETS in code: max tool calls + wall-clock seconds. On breach we force a
     final report_findings call so output is always structured.

The model backend is chosen by FMAJ_LLM_PROVIDER (bedrock|gemini) — see providers.py.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from fmaj_agent import config, role_match
from fmaj_agent.budget import NoSharedBudget, SearchBudget
from fmaj_agent.models import Company, Findings, OpportunityType
from fmaj_agent.providers import get_provider
from fmaj_agent.tools.impl import RECRUITMENT_EMAIL
from fmaj_agent.tools import (
    extract_emails,
    fetch_url,
    find_careers_link,
    find_seek_company_page,
    search_jobs_adzuna,
    web_search,
)
from fmaj_agent.trace import (
    StepSink,
    Tag,
    TraceStep,
    noop_sink,
    summarise_tool_result,
)

logger = logging.getLogger(__name__)

_SYSTEM = (Path(__file__).parent / "prompts" / "system.md").read_text()

#: Tools with their own per-company budget on top of the shared tool-call limit.
#: SerpAPI's free tier is ~250 searches a MONTH, so `web_search` is metered
#: separately — see the arithmetic in config.py.
_METERED = {"web_search": lambda: config.MAX_WEB_SEARCHES}

def _dispatch_for(company: Company) -> dict:
    """Tool name -> callable, with this company's context already bound.

    The country is bound here rather than exposed as a tool argument on purpose:
    it is a fact we read off the Places result, and the model has no way to know
    it better than we do. Letting it pass a country would let a hallucinated "au"
    send a Berlin bakery to the Australian job index — the exact failure that made
    the app AU-only in the first place.
    """
    country = company.country_code
    return {
        "fetch_url": lambda a: fetch_url(a["url"]),
        "find_careers_link": lambda a: find_careers_link(a["url"]),
        "search_jobs_adzuna": lambda a: search_jobs_adzuna(
            a["company"], a["role"], country_code=country
        ),
        "find_seek_company_page": lambda a: find_seek_company_page(
            a["company"], country_code=country
        ),
        "web_search": lambda a: web_search(a["query"]),
        "extract_emails": lambda a: extract_emails(a["url"]),
    }


@dataclass
class AgentRun:
    findings: Findings
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    trace: list[str] = field(default_factory=list)
    #: Calls per metered tool, so a run's paid-API spend is visible afterwards.
    metered_calls: dict[str, int] = field(default_factory=dict)
    # Set when the run aborted due to an infrastructure failure (network/model),
    # NOT because the agent legitimately found nothing. Callers must not treat
    # these as real findings.
    error: str | None = None
    #: Every vacancy title a tool put in front of the model this run, lowercased
    #: -> as written. Provenance for the report gate: a title the agent never saw
    #: cannot be the one it claims to have matched.
    observed_titles: dict[str, str] = field(default_factory=dict)
    #: Of those, the ones `role_match` cleared as the role sought.
    verified_titles: set[str] = field(default_factory=set)
    #: Emails `extract_emails` actually read off a page, lowercased -> as written.
    #: Provenance again: an address the agent picked out of a search snippet is
    #: not evidence the company reads resumes there.
    observed_emails: dict[str, str] = field(default_factory=dict)
    #: True once any fetched page invited applications ("send us your resume",
    #: "we're hiring"). It is what lets a generic `info@` count as a lead.
    saw_hiring_signal: bool = False

    def stats(self) -> dict:
        return {
            "provider": config.LLM_PROVIDER,
            "error": self.error or "",
            "tool_calls": self.tool_calls,
            "web_searches": self.metered_calls.get("web_search", 0),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "seconds": round(self.seconds, 1),
            "opportunity_type": self.findings.opportunity_type.value,
            "confidence": self.findings.confidence,
        }


#: Hosts whose links only ever mean "there is a vacancy here". If the vacancy
#: turns out not to be the role, the link says nothing at all — unlike a page on
#: the company's own domain, which is still a careers page worth showing. So a
#: downgraded finding keeps the latter and drops the former.
_BOARD_HOSTS = ("seek.com", "seek.co.nz", "linkedin.com", "adzuna.com", "indeed.com",
                "jora.com", "glassdoor.com")

#: A downgraded finding is the model's link with the model's claim removed, so it
#: must not inherit the confidence it had in the claim we just rejected.
DOWNGRADE_CONFIDENCE = 0.5


def _is_board_link(url: str) -> bool:
    """Substring match on the host, deliberately: the boards run a domain per
    market (`au.seek.com`, `seek.com.au`, `uk.indeed.com`, `au.linkedin.com`) and
    the cost of being loose here is dropping one link, while the cost of being
    strict is showing an unverified listing — the bug this all exists for."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return any(h in host for h in _BOARD_HOSTS)


def _verify_listing(findings: Findings, run: AgentRun, roles: list[str]) -> tuple[Findings, str]:
    """A `job_listing` must name a vacancy title that really matches the role.

    This is the backstop behind the per-tool gates. Those catch Seek and Adzuna
    before the model ever sees an off-role vacancy; this catches everything else
    — a listing the model spotted in careers-page text, or a board link it
    inferred from a `web_search` result — and it catches the model claiming a
    listing it cannot point at.

    Returns the findings to use plus a one-line reason when they were downgraded
    ("" when they stand). Downgrading follows the ladder the product asked for:
    a real careers page or a contact email still earns the company a place in the
    results; nothing at all drops it.
    """
    if findings.opportunity_type is not OpportunityType.JOB_LISTING:
        return findings, ""

    title = (findings.matched_title or "").strip()
    key = title.lower()
    if not title:
        why = "reported a live listing without naming the vacancy"
    elif key in run.verified_titles:
        return findings, ""
    elif key in run.observed_titles:
        # Seen, but not yet judged — a title read out of a careers page or a
        # web_search result. Judge it now; the cache makes this usually free.
        if role_match.match_titles([run.observed_titles[key]], roles).matched:
            run.verified_titles.add(key)
            return findings, ""
        why = f'"{title[:48]}" is not the role sought'
    else:
        why = f'no tool returned a vacancy titled "{title[:48]}"'

    links = [url for url in findings.links if not _is_board_link(url)]
    if links:
        otype = OpportunityType.CAREERS_PAGE
    elif findings.emails:
        otype = OpportunityType.CONTACT_EMAIL
    else:
        otype = OpportunityType.NONE
    evidence = f"{findings.evidence} (not a matching listing: {why})".strip()
    return (
        Findings(
            opportunity_type=otype,
            links=links,
            emails=findings.emails,
            evidence=evidence[:600],
            confidence=min(findings.confidence, DOWNGRADE_CONFIDENCE),
            matched_title="",
        ),
        why,
    )


def _verify_email(findings: Findings, run: AgentRun) -> tuple[Findings, str]:
    """A `contact_email` must be an address a resume could plausibly reach.

    "The company has an email" is not a job lead. The case this exists for:
    `sales@trendzit.com.au`, reported for a company whose site was down, scraped
    out of a directory listing, with no vacancy anywhere — a real address that
    nobody there reads resumes at. Against it, `hr@starboardit.com` off a page
    saying "please send us your resume" is exactly what the product is for.

    Two conditions, both cheap and both deterministic:

    * **Provenance** — the address came back from `extract_emails`, i.e. we read
      it off a page, rather than out of a `web_search` snippet.
    * **Plausibility** — either the mailbox is labelled for hiring
      (`careers@`, `hr@` …) or some page we fetched invited applications, which
      is what keeps the cafe whose only address is `info@`.

    Nothing survives -> `none`, and the company drops out. Its links go too: a
    `contact_email` finding only ever links to the contact page it found the
    address on, and that is not worth a card of its own.
    """
    if findings.opportunity_type is not OpportunityType.CONTACT_EMAIL:
        return findings, ""

    kept, unseen, weak = [], [], []
    for email in findings.emails:
        key = email.strip().lower()
        if key not in run.observed_emails:
            unseen.append(email)
        elif RECRUITMENT_EMAIL.match(key) or run.saw_hiring_signal:
            kept.append(run.observed_emails[key])
        else:
            weak.append(email)

    if kept:
        return findings.model_copy(update={"emails": kept}), ""

    if unseen:
        why = f'"{unseen[0][:40]}" was not read off the company\'s own page'
    elif weak:
        why = f'"{weak[0][:40]}" is not a hiring address and nothing invited applications'
    else:
        why = "no usable contact address"
    return (
        Findings(
            opportunity_type=OpportunityType.NONE,
            evidence=f"{findings.evidence} (dropped: {why})".strip()[:600],
            confidence=min(findings.confidence, DOWNGRADE_CONFIDENCE),
        ),
        why,
    )


def _verify(findings: Findings, run: AgentRun, roles: list[str]) -> tuple[Findings, str]:
    """Every claim the model makes about a company, checked against what the
    tools actually returned. One door, so no report path can skip it."""
    findings, why = _verify_listing(findings, run, roles)
    if why:
        return findings, why
    return _verify_email(findings, run)


def _over_budget(run: AgentRun, tool: str, budget: SearchBudget) -> str | None:
    """Reserve one call of a metered tool. Returns a refusal reason, or None.

    Two gates, in-process first: the per-company cap costs nothing to check, so
    checking it first avoids a DynamoDB write for a call we were going to refuse
    anyway.

    Counts the call only when both allow it, so `metered_calls` records real
    paid-API usage rather than attempts.
    """
    if tool not in _METERED:
        return None
    cap = _METERED[tool]()
    used = run.metered_calls.get(tool, 0)
    if cap and used >= cap:  # cap == 0 means unlimited
        return f"budget reached: {cap} {tool} call(s) per company"
    denial = budget.reserve(tool)
    if denial is not None:
        return denial
    run.metered_calls[tool] = used + 1
    return None


def _emit(sink: StepSink, step: TraceStep) -> None:
    """Publish a trace step. A broken sink must never fail the investigation —
    the panel is a view onto the work, not the work itself."""
    try:
        sink(step)
    except Exception:  # noqa: BLE001
        logger.warning("trace sink failed for %s", step.tool, exc_info=True)


def _model() -> str:
    return config.GEMINI_MODEL if config.LLM_PROVIDER == "gemini" else config.AGENT_MODEL


def _triage_model() -> str:
    return config.GEMINI_MODEL if config.LLM_PROVIDER == "gemini" else config.TRIAGE_MODEL


def _triage(company: Company, run: AgentRun) -> bool:
    prompt = (
        f"Company: {company.name}\nTypes: {', '.join(company.types)}\n"
        f"Address: {company.address}\nRoles sought: {', '.join(company.roles)}\n\n"
        "Could this business plausibly employ someone in one of those roles? "
        'Answer ONLY compact JSON: {"plausible": true|false}.'
    )
    turn = get_provider().complete(
        "", [{"role": "user", "text": prompt}],
        model=_triage_model(), use_tools=False, max_tokens=50,
    )
    run.input_tokens += turn.input_tokens
    run.output_tokens += turn.output_tokens
    text = turn.text
    try:
        return bool(json.loads(text[text.index("{"): text.rindex("}") + 1])["plausible"])
    except Exception:
        return True  # on parse failure, don't wrongly discard


def _findings_from_report(args: dict) -> Findings:
    try:
        otype = OpportunityType(args.get("opportunity_type", "none"))
    except ValueError:
        otype = OpportunityType.NONE
    return Findings(
        opportunity_type=otype,
        links=args.get("links", []) or [],
        emails=args.get("emails", []) or [],
        evidence=args.get("evidence", ""),
        confidence=float(args.get("confidence", 0.0) or 0.0),
        matched_title=str(args.get("matched_title", "") or "")[:120],
    )


def investigate(
    company: Company,
    on_step: StepSink = noop_sink,
    budget: SearchBudget | None = None,
) -> AgentRun:
    """Run the full investigation for one company. Never raises.

    `on_step` is called as each tool completes so the UI can show the run while
    it is still happening. A sink that throws must never take the search down
    with it — see `_emit`.

    `budget` meters paid tools across every company in the same search. Defaults
    to no shared ceiling, which is right for a local run: there is only one
    company in flight, so the per-company cap already is the per-search cap.
    """
    budget = budget or NoSharedBudget()
    run = AgentRun(findings=Findings(opportunity_type=OpportunityType.NONE))
    dispatch = _dispatch_for(company)
    start = time.monotonic()

    def emit(tag: Tag, tool: str, meta: str = "") -> None:
        _emit(on_step, TraceStep(tag=tag, tool=tool, text=company.name,
                                 meta=meta, place_id=company.place_id))

    try:
        provider = get_provider()
        if not _triage(company, run):
            emit(Tag.SKIPPING, "triage", "not a likely employer")
            run.findings = Findings(
                opportunity_type=OpportunityType.NONE,
                evidence="triage: not a plausible employer for the role",
                confidence=0.7,
            )
            run.seconds = time.monotonic() - start
            return run
        emit(Tag.CHECKING, "triage", "worth a look")

        user = (
            f"Investigate this company for job opportunities.\n"
            f"Name: {company.name}\nWebsite: {company.website or 'unknown'}\n"
            f"Address: {company.address}\nRoles: {', '.join(company.roles)}\n"
            # The country is stated so web_search queries can be aimed at boards
            # that actually cover it. Which country-specific tools are *available*
            # is still enforced in code, not here — the tools refuse on their own.
            f"Country: {(company.country_code or 'unknown').upper()}\n\n"
            "Find the best opportunity (live listing > careers page > contact email), "
            "then call report_findings."
        )
        messages: list[dict] = [{"role": "user", "text": user}]

        # Read off `config` at call time rather than copied into module constants,
        # so overriding the budget is a one-line change in one place (and tests
        # can patch it). 0 = unlimited — see config.py for the arithmetic.
        max_calls = config.MAX_TOOL_CALLS or float("inf")
        max_seconds = config.MAX_SECONDS or float("inf")

        while run.tool_calls < max_calls and (time.monotonic() - start) < max_seconds:
            turn = provider.complete(_SYSTEM, messages, model=_model(), max_tokens=1024)
            run.input_tokens += turn.input_tokens
            run.output_tokens += turn.output_tokens
            messages.append({"role": "assistant", "text": turn.text,
                             "tool_uses": turn.tool_uses})

            if not turn.tool_uses:
                break  # model stopped without a tool

            results = []
            done = False
            for tu in turn.tool_uses:
                run.trace.append(f"{tu.name}({tu.input})")
                if tu.name == "report_findings":
                    findings, downgraded = _verify(
                        _findings_from_report(tu.input), run, company.roles
                    )
                    run.findings = findings
                    done = True
                    if downgraded:
                        # The panel promises nothing hidden, so a rejected claim
                        # is a visible row, not a silent rewrite.
                        emit(Tag.SKIPPING, "role_match", downgraded[:60])
                    emit(
                        Tag.FOUND
                        if run.findings.opportunity_type is not OpportunityType.NONE
                        else Tag.SKIPPING,
                        "report_findings",
                        run.findings.opportunity_type.value.replace("_", " "),
                    )
                    results.append({"id": tu.id, "name": tu.name, "output": {"ok": True}})
                    continue
                run.tool_calls += 1

                denial = _over_budget(run, tu.name, budget)
                if denial is not None:
                    # Refuse rather than silently dropping the call: the model is
                    # told why, so it can fall back to a cheaper source, and the
                    # trace shows the refusal instead of a phantom step.
                    emit(Tag.SKIPPING, tu.name, denial)
                    results.append({"id": tu.id, "name": tu.name,
                                    "output": {"ok": False, "reason": denial}})
                    continue

                result = dispatch[tu.name](tu.input) if tu.name in dispatch else None
                # Record what the model is about to see BEFORE gating, so the
                # report gate can tell "you never saw that title" apart from
                # "you saw it and it wasn't the role".
                for title in role_match.observed_titles(tu.name, result):
                    run.observed_titles.setdefault(title.lower(), title)
                if result is not None and result.ok:
                    if result.data.get("hiring_signal"):
                        run.saw_hiring_signal = True
                    if tu.name == "extract_emails":
                        for email in result.data.get("emails") or []:
                            run.observed_emails.setdefault(str(email).lower(), email)
                gate = role_match.GATES.get(tu.name)
                if gate is not None and result is not None and company.roles:
                    result, report = gate(result, company.roles)
                    if report is not None:
                        run.verified_titles |= {t.lower() for t in report.titles}
                output = result.model_dump() if result else {"ok": False, "reason": "unknown"}
                tag, meta = summarise_tool_result(tu.name, tu.input, result)
                emit(tag, tu.name, meta)
                results.append({"id": tu.id, "name": tu.name, "output": output})
            messages.append({"role": "tool", "results": results})
            if done:
                run.seconds = time.monotonic() - start
                return run

        run.findings, downgraded = _verify(
            _force_report(provider, messages, run), run, company.roles
        )
        if downgraded:
            emit(Tag.SKIPPING, "role_match", downgraded[:60])
    except Exception as exc:  # noqa: BLE001 — one company's failure must not crash the batch
        logger.exception("agent failed for %s", company.name)
        run.error = f"{type(exc).__name__}: {exc}"[:200]
        emit(Tag.SKIPPING, "triage", f"error: {type(exc).__name__}")
        run.findings = Findings(
            opportunity_type=OpportunityType.NONE,
            evidence=f"agent error: {type(exc).__name__}",
            confidence=0.0,
        )
    run.seconds = time.monotonic() - start
    return run


def _force_report(provider, messages: list[dict], run: AgentRun) -> Findings:
    """Force report_findings so we always end with structured output."""
    messages.append({"role": "user", "text":
        "Budget reached. Call report_findings now with what you found so far."})
    try:
        turn = provider.complete(_SYSTEM, messages, model=_model(),
                                 force_tool="report_findings", max_tokens=512)
        run.input_tokens += turn.input_tokens
        run.output_tokens += turn.output_tokens
        for tu in turn.tool_uses:
            if tu.name == "report_findings":
                return _findings_from_report(tu.input)
    except Exception:  # noqa: BLE001
        logger.warning("forced report failed")
    return Findings(opportunity_type=OpportunityType.NONE,
                    evidence="budget exhausted, no finding", confidence=0.0)
