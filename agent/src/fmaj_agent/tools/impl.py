"""Tool implementations. Every tool returns a ToolResult and NEVER raises.

Conduct rules (docs/PLAN.md §4): respect robots.txt, honest User-Agent, short
timeouts, a few pages per site, never bypass logins/captchas. Seek/LinkedIn are
never scraped — only linked to via web_search.
"""
import re
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from fmaj_agent import secrets
from fmaj_agent.models import ToolResult

USER_AGENT = "FindMeAJobBot/0.1 (+https://findmeajob.example/bot)"
TIMEOUT = 10.0
MAX_CHARS = 4000

CAREERS_PATTERNS = re.compile(
    r"(career|careers|jobs|join[-\s]?us|work[-\s]?with[-\s]?us|employment|vacanc|"
    r"positions|hiring|work[-\s]?here|team|recruit)",
    re.I,
)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PREFERRED_EMAIL = re.compile(r"^(careers?|jobs?|hr|recruit\w*|people|work)@", re.I)

_robot_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


def _allowed(url: str) -> bool:
    """robots.txt check; on any doubt/error, allow (fail-open, we fetch few pages).

    Fetched via httpx WITH a timeout — RobotFileParser.read() uses urllib with no
    timeout and hangs forever on hosts that black-hole bot connections.
    """
    try:
        parts = urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
        rp = _robot_cache.get(root)
        if root not in _robot_cache:
            rp = None
            try:
                resp = httpx.get(f"{root}/robots.txt", timeout=5,
                                 headers={"User-Agent": USER_AGENT},
                                 follow_redirects=True)
                if resp.status_code == 200:
                    parser = urllib.robotparser.RobotFileParser()
                    parser.parse(resp.text.splitlines())
                    rp = parser
            except Exception:
                rp = None  # unreachable/unreadable -> allow
            _robot_cache[root] = rp  # type: ignore[assignment]
        return rp.can_fetch(USER_AGENT, url) if rp else True
    except Exception:
        return True


def _get(url: str) -> httpx.Response:
    return httpx.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
        follow_redirects=True,
    )


def fetch_url(url: str) -> ToolResult:
    """Fetch a page and readability-extract the main text (truncated)."""
    if not _allowed(url):
        return ToolResult(ok=False, reason="blocked by robots.txt")
    try:
        resp = _get(url)
        if resp.is_error:
            return ToolResult(ok=False, reason=f"http {resp.status_code}")
        text = trafilatura.extract(resp.text) or ""
        return ToolResult(
            ok=True,
            data={"url": str(resp.url), "text": text[:MAX_CHARS], "html_len": len(resp.text)},
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, reason=f"{type(exc).__name__}: {exc}")


def find_careers_link(url: str) -> ToolResult:
    """Scan a homepage for careers/jobs links (cheap heuristic before LLM reasoning)."""
    if not _allowed(url):
        return ToolResult(ok=False, reason="blocked by robots.txt")
    try:
        resp = _get(url)
        if resp.is_error:
            return ToolResult(ok=False, reason=f"http {resp.status_code}")
        found: list[str] = []
        seen = set()
        for m in re.finditer(r'href=["\']([^"\']+)["\']([^>]*)>([^<]*)', resp.text, re.I):
            href, _, label = m.groups()
            if CAREERS_PATTERNS.search(href) or CAREERS_PATTERNS.search(label):
                absolute = urljoin(str(resp.url), href)
                if absolute not in seen and absolute.startswith("http"):
                    seen.add(absolute)
                    found.append(absolute)
        return ToolResult(ok=True, data={"candidates": found[:5]})
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, reason=f"{type(exc).__name__}: {exc}")


def search_jobs_adzuna(company: str, role: str, location: str = "australia") -> ToolResult:
    """Official Adzuna API job search, scoped to AU and the company name."""
    try:
        app_id, app_key = secrets.adzuna_credentials()
        resp = httpx.get(
            "https://api.adzuna.com/v1/api/jobs/au/search/1",
            params={
                "app_id": app_id,
                "app_key": app_key,
                "what": f"{role} {company}",
                "what_and": company,
                "results_per_page": 10,
                "content-type": "application/json",
            },
            timeout=TIMEOUT,
        )
        if resp.is_error:
            return ToolResult(ok=False, reason=f"http {resp.status_code}: {resp.text[:200]}")
        results = resp.json().get("results", [])
        jobs = [
            {
                "title": j.get("title"),
                "company": (j.get("company") or {}).get("display_name"),
                "location": (j.get("location") or {}).get("display_name"),
                "url": j.get("redirect_url"),
            }
            for j in results
        ]
        return ToolResult(ok=True, data={"jobs": jobs})
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, reason=f"{type(exc).__name__}: {exc}")


def web_search(query: str) -> ToolResult:
    """SerpAPI Google search. Used for site:seek.com.au / site:linkedin.com/jobs lookups.

    Returns organic result links only — we never scrape Seek/LinkedIn pages.
    """
    try:
        resp = httpx.get(
            "https://serpapi.com/search",
            params={"engine": "google", "q": query, "num": 10, "api_key": secrets.serpapi_key()},
            timeout=TIMEOUT,
        )
        if resp.is_error:
            return ToolResult(ok=False, reason=f"http {resp.status_code}: {resp.text[:200]}")
        organic = resp.json().get("organic_results", [])
        links = [
            {"title": r.get("title"), "link": r.get("link"), "snippet": r.get("snippet")}
            for r in organic
            if r.get("link")
        ]
        return ToolResult(ok=True, data={"results": links[:8]})
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, reason=f"{type(exc).__name__}: {exc}")


def extract_emails(url: str) -> ToolResult:
    """Scrape a contact/about page for emails, preferring careers@/jobs@/hr@."""
    if not _allowed(url):
        return ToolResult(ok=False, reason="blocked by robots.txt")
    try:
        resp = _get(url)
        if resp.is_error:
            return ToolResult(ok=False, reason=f"http {resp.status_code}")
        emails = sorted(set(EMAIL_RE.findall(resp.text)))
        # drop obvious asset false-positives
        emails = [e for e in emails if not e.lower().endswith((".png", ".jpg", ".webp"))]
        emails.sort(key=lambda e: (not PREFERRED_EMAIL.match(e), e))
        return ToolResult(ok=True, data={"emails": emails[:5]})
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, reason=f"{type(exc).__name__}: {exc}")
