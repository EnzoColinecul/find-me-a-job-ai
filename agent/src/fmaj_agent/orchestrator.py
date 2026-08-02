"""Bedrock Converse tool-use loop — the per-company agent.

Flow (docs/PLAN.md §4):
  1. Haiku triage: is this a plausible employer for the role? If not -> none (cheap).
  2. Tool loop (Converse): the model calls fetch_url / find_careers_link /
     search_jobs_adzuna / web_search / extract_emails, then report_findings.
  3. HARD BUDGETS in code: max tool calls + wall-clock seconds. On breach we force a
     final report_findings call so output is always structured.

Every model call's token usage is accumulated and logged.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import boto3

from fmaj_agent import config
from fmaj_agent.models import Company, Findings, OpportunityType
from fmaj_agent.tools import (
    extract_emails,
    fetch_url,
    find_careers_link,
    search_jobs_adzuna,
    web_search,
)

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 8
MAX_SECONDS = 60
_SYSTEM = (Path(__file__).parent / "prompts" / "system.md").read_text()

# Tool schemas exposed to the model (Converse toolConfig format).
_TOOL_SPECS = [
    {
        "toolSpec": {
            "name": "fetch_url",
            "description": "Fetch a web page and return its main text (truncated).",
            "inputSchema": {"json": {"type": "object", "properties": {
                "url": {"type": "string"}}, "required": ["url"]}},
        }
    },
    {
        "toolSpec": {
            "name": "find_careers_link",
            "description": "Scan a company homepage for careers/jobs page links.",
            "inputSchema": {"json": {"type": "object", "properties": {
                "url": {"type": "string"}}, "required": ["url"]}},
        }
    },
    {
        "toolSpec": {
            "name": "search_jobs_adzuna",
            "description": "Search Adzuna (AU job board) for live postings at a company.",
            "inputSchema": {"json": {"type": "object", "properties": {
                "company": {"type": "string"}, "role": {"type": "string"}},
                "required": ["company", "role"]}},
        }
    },
    {
        "toolSpec": {
            "name": "web_search",
            "description": (
                "Google search (SerpAPI). Use site:seek.com.au or site:linkedin.com/jobs "
                "with the company name to find external job listings. Returns links only."
            ),
            "inputSchema": {"json": {"type": "object", "properties": {
                "query": {"type": "string"}}, "required": ["query"]}},
        }
    },
    {
        "toolSpec": {
            "name": "extract_emails",
            "description": "Scrape a contact/about page for recruitment emails.",
            "inputSchema": {"json": {"type": "object", "properties": {
                "url": {"type": "string"}}, "required": ["url"]}},
        }
    },
    {
        "toolSpec": {
            "name": "report_findings",
            "description": "Report the final result. Call exactly once when done.",
            "inputSchema": {"json": {"type": "object", "properties": {
                "opportunity_type": {"type": "string",
                    "enum": ["careers_page", "job_listing", "contact_email", "none"]},
                "links": {"type": "array", "items": {"type": "string"}},
                "emails": {"type": "array", "items": {"type": "string"}},
                "evidence": {"type": "string"},
                "confidence": {"type": "number"}},
                "required": ["opportunity_type", "evidence", "confidence"]}},
        }
    },
]

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

    def stats(self) -> dict:
        return {
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "seconds": round(self.seconds, 1),
            "opportunity_type": self.findings.opportunity_type.value,
            "confidence": self.findings.confidence,
        }


def _client():
    return boto3.client("bedrock-runtime", region_name=config.AWS_REGION)


def _triage(company: Company, run: AgentRun) -> bool:
    """Cheap Haiku yes/no: is this a plausible employer for the role(s)?"""
    prompt = (
        f"Company: {company.name}\nTypes: {', '.join(company.types)}\n"
        f"Address: {company.address}\nRoles sought: {', '.join(company.roles)}\n\n"
        "Could this business plausibly employ someone in one of those roles? "
        'Answer ONLY compact JSON: {"plausible": true|false}.'
    )
    resp = _client().converse(
        modelId=config.TRIAGE_MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 50, "temperature": 0},
    )
    usage = resp.get("usage", {})
    run.input_tokens += usage.get("inputTokens", 0)
    run.output_tokens += usage.get("outputTokens", 0)
    text = resp["output"]["message"]["content"][0]["text"]
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


def investigate(company: Company) -> AgentRun:
    """Run the full investigation for one company. Never raises."""
    run = AgentRun(findings=Findings(opportunity_type=OpportunityType.NONE))
    start = time.monotonic()
    try:
        if not _triage(company, run):
            run.findings = Findings(
                opportunity_type=OpportunityType.NONE,
                evidence="triage: not a plausible employer for the role",
                confidence=0.7,
            )
            run.seconds = time.monotonic() - start
            return run

        user = (
            f"Investigate this company for job opportunities.\n"
            f"Name: {company.name}\nWebsite: {company.website or 'unknown'}\n"
            f"Address: {company.address}\nRoles: {', '.join(company.roles)}\n\n"
            "Find the best opportunity (live listing > careers page > contact email), "
            "then call report_findings."
        )
        messages = [{"role": "user", "content": [{"text": user}]}]
        client = _client()

        while run.tool_calls < MAX_TOOL_CALLS and (time.monotonic() - start) < MAX_SECONDS:
            resp = client.converse(
                modelId=config.AGENT_MODEL,
                system=[{"text": _SYSTEM}],
                messages=messages,
                toolConfig={"tools": _TOOL_SPECS},
                inferenceConfig={"maxTokens": 1024, "temperature": 0},
            )
            usage = resp.get("usage", {})
            run.input_tokens += usage.get("inputTokens", 0)
            run.output_tokens += usage.get("outputTokens", 0)
            out = resp["output"]["message"]
            messages.append(out)

            tool_uses = [c["toolUse"] for c in out["content"] if "toolUse" in c]
            if not tool_uses:
                break  # model stopped without a tool; exit loop

            tool_results = []
            done = False
            for tu in tool_uses:
                name, args, tid = tu["name"], tu.get("input", {}), tu["toolUseId"]
                run.trace.append(f"{name}({args})")
                if name == "report_findings":
                    run.findings = _findings_from_report(args)
                    done = True
                    tool_results.append({"toolResult": {"toolUseId": tid,
                        "content": [{"text": "ok"}]}})
                    continue
                run.tool_calls += 1
                result = _DISPATCH[name](args) if name in _DISPATCH else None
                payload = result.model_dump() if result else {"ok": False, "reason": "unknown tool"}
                tool_results.append({"toolResult": {"toolUseId": tid,
                    "content": [{"json": payload}]}})
            messages.append({"role": "user", "content": tool_results})
            if done:
                run.seconds = time.monotonic() - start
                return run

        # budget exhausted without report -> force a final structured answer
        run.findings = _force_report(client, messages, run)
    except Exception as exc:  # noqa: BLE001 — one company's failure must not crash the batch
        logger.exception("agent failed for %s", company.name)
        run.findings = Findings(
            opportunity_type=OpportunityType.NONE,
            evidence=f"agent error: {type(exc).__name__}",
            confidence=0.0,
        )
    run.seconds = time.monotonic() - start
    return run


def _force_report(client, messages: list, run: AgentRun) -> Findings:
    """Force report_findings via toolChoice so we always end with structured output."""
    messages.append({"role": "user", "content": [{"text":
        "Budget reached. Call report_findings now with what you found so far."}]})
    try:
        resp = client.converse(
            modelId=config.AGENT_MODEL,
            system=[{"text": _SYSTEM}],
            messages=messages,
            toolConfig={"tools": _TOOL_SPECS,
                        "toolChoice": {"tool": {"name": "report_findings"}}},
            inferenceConfig={"maxTokens": 512, "temperature": 0},
        )
        usage = resp.get("usage", {})
        run.input_tokens += usage.get("inputTokens", 0)
        run.output_tokens += usage.get("outputTokens", 0)
        for c in resp["output"]["message"]["content"]:
            if "toolUse" in c and c["toolUse"]["name"] == "report_findings":
                return _findings_from_report(c["toolUse"].get("input", {}))
    except Exception:  # noqa: BLE001
        logger.warning("forced report failed")
    return Findings(opportunity_type=OpportunityType.NONE,
                    evidence="budget exhausted, no finding", confidence=0.0)
