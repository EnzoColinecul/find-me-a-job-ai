"""Agent tools. Each is deterministic, typed, and never raises (returns ToolResult)."""
from fmaj_agent.tools.impl import (
    extract_emails,
    fetch_url,
    find_careers_link,
    search_jobs_adzuna,
    web_search,
)

__all__ = [
    "fetch_url",
    "find_careers_link",
    "search_jobs_adzuna",
    "web_search",
    "extract_emails",
]
