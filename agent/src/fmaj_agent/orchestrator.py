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

from fmaj_agent import config
from fmaj_agent.models import Company, Findings, OpportunityType
from fmaj_agent.providers import get_provider
from fmaj_agent.tools import (
    extract_emails,
    fetch_url,
    find_careers_link,
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

MAX_TOOL_CALLS = 8
MAX_SECONDS = 60
_SYSTEM = (Path(__file__).parent / "prompts" / "system.md").read_text()

_DISPATCH = {
    "fetch_url": lambda a: fetch_url(a["url"]),
    "find_careers_link": lambda a: find_careers_link(a["url"]),
    "search_jobs_adzuna": lambda a: search_jobs_adzuna(a["company"], a["role"]),
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
    # Set when the run aborted due to an infrastructure failure (network/model),
    # NOT because the agent legitimately found nothing. Callers must not treat
    # these as real findings.
    error: str | None = None

    def stats(self) -> dict:
        return {
            "provider": config.LLM_PROVIDER,
            "error": self.error or "",
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "seconds": round(self.seconds, 1),
            "opportunity_type": self.findings.opportunity_type.value,
            "confidence": self.findings.confidence,
        }


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
    )


def investigate(company: Company, on_step: StepSink = noop_sink) -> AgentRun:
    """Run the full investigation for one company. Never raises.

    `on_step` is called as each tool completes so the UI can show the run while
    it is still happening. A sink that throws must never take the search down
    with it — see `_emit`.
    """
    run = AgentRun(findings=Findings(opportunity_type=OpportunityType.NONE))
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
            f"Address: {company.address}\nRoles: {', '.join(company.roles)}\n\n"
            "Find the best opportunity (live listing > careers page > contact email), "
            "then call report_findings."
        )
        messages: list[dict] = [{"role": "user", "text": user}]

        while run.tool_calls < MAX_TOOL_CALLS and (time.monotonic() - start) < MAX_SECONDS:
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
                    run.findings = _findings_from_report(tu.input)
                    done = True
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
                result = _DISPATCH[tu.name](tu.input) if tu.name in _DISPATCH else None
                output = result.model_dump() if result else {"ok": False, "reason": "unknown"}
                tag, meta = summarise_tool_result(tu.name, tu.input, result)
                emit(tag, tu.name, meta)
                results.append({"id": tu.id, "name": tu.name, "output": output})
            messages.append({"role": "tool", "results": results})
            if done:
                run.seconds = time.monotonic() - start
                return run

        run.findings = _force_report(provider, messages, run)
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
