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


#: Countries Adzuna publishes a job index for. The API takes the code as a PATH
#: segment (`/v1/api/jobs/{country}/search/1`), so an unsupported one is a 404,
#: not an empty result set — we check before spending the call.
#: Source: https://developer.adzuna.com/overview (verified 2026-08-15).
ADZUNA_COUNTRIES = frozenset({
    "at", "au", "be", "br", "ca", "ch", "de", "es", "fr", "gb",
    "in", "it", "mx", "nl", "nz", "pl", "sg", "us", "za",
})


def search_jobs_adzuna(
    company: str, role: str, country_code: str | None = None
) -> ToolResult:
    """Official Adzuna API job search for one company, in that company's country.

    `country_code` is ISO-3166 alpha-2, taken from the Places result for this
    company (see `discovery._country_code`) — NOT chosen by the model. It used to
    be hardcoded to `au`, which meant a search run from London queried the
    Australian index and always came back empty.

    Unknown or unsupported country -> a refusal the model can read and route
    around, never a silent wrong-country query. The trace shows it as `Skipping`.
    """
    country = (country_code or "").strip().lower()
    if not country:
        return ToolResult(
            ok=False,
            reason="no country known for this company — cannot pick a job index",
        )
    if country not in ADZUNA_COUNTRIES:
        return ToolResult(
            ok=False,
            reason=f"Adzuna has no job index for {country.upper()} — try the "
                   "company's own site, or web_search as a last resort",
        )
    try:
        app_id, app_key = secrets.adzuna_credentials()
        resp = httpx.get(
            f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
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


SEEK_COMPANY_URL = "https://au.seek.com/{slug}-jobs/at-this-company"

#: Seek's employer pages only cover Australian employers, and the robots.txt
#: analysis behind the one deliberate fetch exception (CLAUDE.md § LLM provider)
#: was done against `au.seek.com` specifically. Calling it for a company in
#: another country is a wasted tool call at best and a wrong link at worst, so
#: the tool refuses outside AU rather than guessing at a sibling domain. Adding
#: `nz.seek.co.nz` would need its own robots.txt check first — don't assume.
SEEK_COUNTRIES = frozenset({"au"})

# Trailing legal suffixes Seek usually omits from its employer-page slugs.
_SEEK_SUFFIX_RE = re.compile(
    r"[\s,]*\b(pty\.?\s*ltd\.?|pty\.?\s*limited|limited|ltd\.?|inc\.?|llc|corp\.?)\s*$",
    re.I,
)

# Seek server-renders its employer pages, so one GET distinguishes a page with
# vacancies from an empty one WITHOUT executing JavaScript. Verified 2026-08-11:
#   Boxtech          -> 515,079 bytes, "No matching search results" x1, jobTitle x0
#   Virtual-IT-Group -> 565,218 bytes, "No matching search results" x0, jobTitle x3
_SEEK_JOB_MARKER = re.compile(r'data-automation="jobTitle"')
_SEEK_EMPTY_MARKER = re.compile(r"No matching search results", re.I)


def _seek_company_slug(company: str) -> str:
    """Slugify a company name into Seek's employer-page format.

    Seek employer pages look like ``au.seek.com/Virtual-IT-Group-jobs/at-this-company``:
    words joined by single hyphens, ``&`` spelled "and", trailing legal suffixes
    (Pty Ltd, Ltd, …) dropped, other punctuation removed. Best-effort only — the URL
    is always validated to resolve before we trust it, so an imperfect slug just
    means we fall back rather than surface a wrong link.
    """
    s = company.strip().replace("&", " and ")
    s = _SEEK_SUFFIX_RE.sub("", s).strip()
    s = re.sub(r"[^0-9A-Za-z\s-]", "", s)      # keep alphanumerics, space, hyphen
    s = re.sub(r"[\s-]+", "-", s).strip("-")   # runs of space/hyphen -> one hyphen
    return s


def find_seek_company_page(company: str, country_code: str | None = None) -> ToolResult:
    """Return Seek's employer listings page for a company ONLY if it has vacancies.

    Australia only — see `SEEK_COUNTRIES`. `country_code` comes from the Places
    result for this company, not from the model; anything else refuses up front
    so an overseas search doesn't spend a tool call on a page that cannot exist.

    Prefers ``au.seek.com/{slug}-jobs/at-this-company`` — Seek's per-employer page —
    over a blind keyword search, which treats the company name as a search term and
    surfaces unrelated employers.

    A slug that matches no employer still returns **HTTP 200** with a rendered
    "No matching search results" page, so status alone proves nothing — an earlier
    HEAD-only version of this shipped links to empty pages. We therefore require
    POSITIVE evidence of at least one vacancy before returning a link.

    Conduct: this counts job markers to decide whether to link, and keeps only the
    count — no titles, descriptions or other listing content are extracted or
    stored. ``/{slug}-jobs/at-this-company`` carries no ``/job/`` segment and no
    query string, so Seek's robots.txt permits it for our user-agent; `_allowed`
    re-checks that at call time and refuses if it ever changes.
    """
    country = (country_code or "").strip().lower()
    if country not in SEEK_COUNTRIES:
        where = country.upper() if country else "an unknown country"
        return ToolResult(
            ok=False,
            reason=f"Seek covers Australia only — this company is in {where}",
        )
    slug = _seek_company_slug(company)
    if not slug:
        return ToolResult(ok=False, reason="could not build a Seek slug")
    url = SEEK_COMPANY_URL.format(slug=slug)
    if not _allowed(url):
        return ToolResult(ok=False, reason="blocked by robots.txt")
    try:
        resp = _get(url)
        if resp.is_error:
            return ToolResult(ok=False, reason=f"http {resp.status_code}")
        if "at-this-company" not in urlparse(str(resp.url)).path:
            return ToolResult(ok=False, reason="no employer page (redirected to search)")
        html = resp.text
        # The empty-state banner wins over any job marker. On the observed empty page
        # there were none, but if Seek ever adds "similar jobs" cards to it, counting
        # markers alone would resurrect exactly the bug this guards against.
        if _SEEK_EMPTY_MARKER.search(html):
            return ToolResult(ok=False, reason="employer page has no current listings")
        jobs = len(_SEEK_JOB_MARKER.findall(html))
        if jobs:
            return ToolResult(
                ok=True,
                data={"url": str(resp.url), "job_count": jobs, "company": company},
            )
        # Neither marker: Seek's markup probably changed. Fail CLOSED — surfacing a
        # link we can't vouch for is the bug this function exists to prevent — but
        # say so distinctly, so the trace shows a broken detector rather than an
        # employer that genuinely has no openings.
        return ToolResult(ok=False, reason="could not confirm listings (markup changed?)")
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
