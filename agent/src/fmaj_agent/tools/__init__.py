"""Agent tools. Each is deterministic, typed, and never raises (returns ToolResult).

Implementation tracked in Notion card: "Build agent tools".
"""
from fmaj_agent.models import ToolResult


def fetch_url(url: str) -> ToolResult:
    """Fetch a page, readability-extract, truncate to ~4K chars.

    Rules: respect robots.txt, 10s timeout, honest User-Agent, max 5 pages/site.
    """
    raise NotImplementedError  # TODO(Phase 3)


def find_careers_link(url: str) -> ToolResult:
    """Scan homepage nav/footer for careers|jobs|join|work-with-us|employment links."""
    raise NotImplementedError  # TODO(Phase 3)


def search_jobs_adzuna(company: str, role: str, location: str) -> ToolResult:
    """Official Adzuna API; fuzzy-match company name."""
    raise NotImplementedError  # TODO(Phase 3)


def web_search(query: str) -> ToolResult:
    """Web search API. Used for site:seek.com.au / site:linkedin.com/jobs lookups.

    NEVER scrape Seek or LinkedIn pages directly — links only (ToS).
    """
    raise NotImplementedError  # TODO(Phase 3)


def extract_emails(url: str) -> ToolResult:
    """Contact/about page scrape: mailto + regex. Prefer careers@/jobs@/hr@/info@."""
    raise NotImplementedError  # TODO(Phase 3)
