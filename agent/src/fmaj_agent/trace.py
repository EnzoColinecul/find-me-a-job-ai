"""Structured trace of what the agent is doing, for the live "What I'm doing" panel.

The panel's promise is "nothing hidden", so the rules here are:

* **Never invent a step.** Every step corresponds to a call we actually made.
* **Never rename a tool into something we don't run.** The mockup shows a
  `places.details` row for a skipped company; we don't call Place Details during
  triage, so that step is labelled `triage`, which is what really happened.
* Display labels live in ONE place (`TOOL_LABELS`) so the panel, and later the
  PDF report, describe the same run the same way.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable


class Tag(str, Enum):
    """Meaning of a row. Maps to tokens: found -> success, checking -> warn."""

    SEARCHING = "searching"
    CHECKING = "checking"
    FOUND = "found"
    SKIPPING = "skipping"


#: Internal tool name -> the label shown to the user. Keep this honest: the
#: right-hand side must name something the agent genuinely does.
TOOL_LABELS: dict[str, str] = {
    "discovery": "places.nearby",
    "triage": "triage",
    "fetch_url": "fetch_page",
    "find_careers_link": "extract_jobs",
    "search_jobs_adzuna": "extract_jobs",
    "find_seek_company_page": "seek.company",
    "web_search": "web_search",
    "extract_emails": "extract_contact",
    "report_findings": "report",
}


def tool_label(name: str) -> str:
    """Friendly label for a tool, falling back to the raw name if unmapped."""
    return TOOL_LABELS.get(name, name)


@dataclass
class TraceStep:
    """One row in the panel: `tag · text · tool · meta`."""

    tag: Tag
    tool: str
    #: What this step is about — usually the company name.
    text: str = ""
    #: The short result, e.g. "9 places found", "2 matches", "no longer trading".
    meta: str = ""
    place_id: str = ""
    at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_item(self) -> dict:
        return {
            "tag": self.tag.value,
            "tool": tool_label(self.tool),
            "text": self.text,
            "meta": self.meta,
            "place_id": self.place_id,
            "at": self.at,
        }


#: A sink the orchestrator calls as work happens. Handlers pass one that writes
#: to DynamoDB; tests and the CLI pass one that collects or prints.
StepSink = Callable[[TraceStep], None]


def noop_sink(_step: TraceStep) -> None:
    """Default: record nothing. Keeps `investigate()` usable without a table."""


def summarise_tool_result(name: str, args: dict, result) -> tuple[Tag, str]:
    """Turn a tool's return value into (tag, meta) for display.

    Deliberately conservative: if we can't tell that something was found, the row
    says "checking", not "found". Over-reporting success in a panel whose whole
    point is transparency would be the worst possible bug here.
    """
    if result is None:
        return Tag.CHECKING, ""

    data = result.model_dump() if hasattr(result, "model_dump") else dict(result)

    if not data.get("ok", True):
        reason = str(data.get("reason") or data.get("error") or "no result")
        return Tag.SKIPPING, reason[:60]

    if name == "search_jobs_adzuna":
        n = len(data.get("jobs") or [])
        return (Tag.FOUND, f"{n} match{'es' if n != 1 else ''}") if n else (
            Tag.CHECKING, "no listings",
        )
    if name == "web_search":
        n = len(data.get("results") or [])
        query = str(args.get("query", ""))[:48]
        return (Tag.FOUND if n else Tag.CHECKING), f'"{query}"'
    if name == "find_seek_company_page":
        return (Tag.FOUND, "employer page") if data.get("url") else (
            Tag.CHECKING, "no page",
        )
    if name == "extract_emails":
        n = len(data.get("emails") or [])
        return (Tag.FOUND, f"{n} email{'s' if n != 1 else ''}") if n else (
            Tag.CHECKING, "no address",
        )
    if name == "find_careers_link":
        url = data.get("url") or ""
        return (Tag.FOUND, "careers page") if url else (Tag.CHECKING, "none found")
    if name == "fetch_url":
        return Tag.CHECKING, _host(str(args.get("url", "")))

    return Tag.CHECKING, ""


def _host(url: str) -> str:
    """Bare hostname for display — the panel has no room for a full URL."""
    try:
        from urllib.parse import urlparse

        return urlparse(url).hostname or url[:40]
    except Exception:  # noqa: BLE001
        return url[:40]
