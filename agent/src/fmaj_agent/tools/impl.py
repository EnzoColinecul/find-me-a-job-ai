"""Tool implementations. Every tool returns a ToolResult and NEVER raises.

Conduct rules (docs/PLAN.md §4): respect robots.txt, honest User-Agent, short
timeouts, a few pages per site, never bypass logins/captchas. Seek/LinkedIn are
never scraped for listing CONTENT — only linked to via web_search. The single
exception is `find_seek_company_page`, which reads the vacancy *titles* off one
robots-allowed employer page to check they match the role; see its docstring.
"""

import ipaddress
import json
import re
import socket
import time
from urllib.parse import urljoin, urlparse

import httpcore
import httpx
import trafilatura
from bs4 import BeautifulSoup

from fmaj_agent import secrets
from fmaj_agent.deadline import bounded_timeout
from fmaj_agent.models import ToolResult

USER_AGENT = "FindMeAJobBot/0.1 (+https://github.com/EnzoColinecul/find-me-a-job-ai)"
TIMEOUT = 10.0
MAX_CHARS = 4000

CAREERS_PATTERNS = re.compile(
    r"(career|careers|jobs|join[-\s]?us|work[-\s]?with[-\s]?us|employment|vacanc|"
    r"positions|hiring|work[-\s]?here|team|recruit)",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

#: Mailboxes somebody deliberately labelled for hiring. A resume sent here has a
#: reader. These are reported on their own evidence.
RECRUITMENT_EMAIL = re.compile(
    r"^(careers?|jobs?|hr|recruit\w*|people|talent|work|employment|hiring|"
    r"apply|applications?)@",
    re.IGNORECASE,
)
PREFERRED_EMAIL = RECRUITMENT_EMAIL  # historical name, kept for callers/tests

#: Mailboxes that are never a job application channel, whatever else the page
#: says. Reporting `sales@` as a way into a company was the complaint that made
#: this list exist: the address is real, and nobody there is reading resumes.
NEVER_EMAIL = re.compile(
    r"^(sales|support|help|helpdesk|billing|account|accounts|accounting|"
    r"invoice|invoices|order|orders|noreply|no-reply|donotreply|do-not-reply|"
    r"privacy|legal|abuse|postmaster|webmaster|marketing|press|media|security|"
    r"unsubscribe|newsletter|spam)@",
    re.IGNORECASE,
)

#: Everything else — `info@`, `contact@`, `hello@`, `admin@` — is often the ONLY
#: address a cafe or a small trades business publishes, so it is not thrown away;
#: it counts only when the company's own page actually invites applications. This
#: pattern is that invitation, and the orchestrator gates generic mailboxes on it.
#: Deliberately phrase-level rather than keyword-level: "careers" in a nav bar is
#: not an invitation, "please send us your resume" is.
HIRING_INVITATION = re.compile(
    r"(send (?:us )?your (?:cv|resum|r\u00e9sum)"
    r"|(?:we(?:\'re| are)|currently)\s+(?:hiring|recruiting)"
    r"|now hiring"
    r"|join (?:our|the) team"
    r"|(?:current|open|available|latest)\s+(?:vacanc|position|role|opportunit)"
    r"|positions? available"
    r"|apply (?:now|online|today|here)"
    r"|(?:job|career|employment) opportunit"
    r"|keen to meet"
    r"|expressions? of interest"
    r"|register your interest)",
    re.IGNORECASE,
)

_robot_cache: dict[str, tuple[float, str | None, int | None]] = {}
ROBOTS_TTL = 3600
MAX_REDIRECTS = 5
BOARD_HOSTS = ("seek.com", "seek.co.nz", "linkedin.com", "indeed.com", "adzuna.com", "jora.com", "glassdoor.com")


def _public_addresses(url: str) -> list[str]:
    """Resolve once and return only addresses suitable for the actual socket."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only public http/https URLs are allowed")
    if parsed.username or parsed.password or parsed.port not in (None, 80, 443):
        raise ValueError("URL credentials or non-standard ports are not allowed")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("private network destinations are not allowed")
    try:
        resolved = [ipaddress.ip_address(host)]
    except ValueError:
        resolved = [
            ipaddress.ip_address(row[4][0])
            for row in socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        ]
    if not resolved or any(not address.is_global for address in resolved):
        raise ValueError("private, loopback, and link-local destinations are not allowed")
    return [str(address) for address in dict.fromkeys(resolved)]


def _safe_destination(url: str) -> tuple[bool, str]:
    """Reject non-web URLs and destinations that resolve to non-public IP space."""
    try:
        _public_addresses(url)
        return True, ""
    except (ValueError, OSError):
        return False, "could not validate destination"


class _PinnedBackend(httpcore.SyncBackend):
    """Connect to validated IPs while TLS still uses the requested hostname."""

    def __init__(self, hostname: str, addresses: list[str]) -> None:
        self.hostname = hostname.encode("idna").decode("ascii").lower().rstrip(".")
        self.addresses = addresses

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        normalized = host.encode("idna").decode("ascii").lower().rstrip(".")
        if normalized != self.hostname:
            raise ValueError("connection host changed after destination validation")
        last_error = None
        for address in self.addresses:
            try:
                return super().connect_tcp(
                    address, port, timeout=timeout, local_address=local_address,
                    socket_options=socket_options,
                )
            except httpcore.NetworkError as exc:  # try the other validated public address
                last_error = exc
        if last_error:
            raise last_error
        raise OSError("no validated public address available")


class _PinnedTransport(httpx.HTTPTransport):
    def __init__(self, hostname: str, addresses: list[str]) -> None:
        super().__init__(trust_env=False)
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False),
            network_backend=_PinnedBackend(hostname, addresses),
            retries=0,
        )


def _send_pinned_request(method: str, url: str, addresses: list[str], timeout: float) -> httpx.Response:
    hostname = urlparse(url).hostname or ""
    with httpx.Client(
        transport=_PinnedTransport(hostname, addresses),
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        follow_redirects=False,
    ) as client:
        return client.request(method, url)


def _board_listing_url(url: str) -> bool:
    """True for board listing bodies; employer-title inspection is separately scoped."""
    try:
        parsed = urlparse(url)
        host, path = (parsed.hostname or "").lower(), parsed.path.lower()
        if not any(host == d or host.endswith("." + d) for d in BOARD_HOSTS):
            return False
        return not (
            "seek.com" in host and path.endswith("/at-this-company") and not parsed.query
        )
    except ValueError:
        return True


def _request_public(url: str, *, purpose: str = "page", timeout: float = TIMEOUT) -> httpx.Response:
    """Follow redirects manually, revalidating DNS/IP and conduct at each hop."""
    current = url
    initial = url
    deadline = time.monotonic() + bounded_timeout(timeout)
    for _ in range(MAX_REDIRECTS + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("outbound request deadline exceeded")
        addresses = _public_addresses(current)
        if purpose == "page" and _board_listing_url(current):
            raise ValueError("fetching job-board listing pages is not permitted")
        if purpose == "page" and current != initial and not _allowed(current):
            raise ValueError("redirect destination is disallowed by robots.txt")
        response = _send_pinned_request("GET", current, addresses, remaining)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        current = urljoin(str(response.url), location)
    raise ValueError("too many redirects")


def _robots_can_fetch(body: str, url: str) -> bool:
    """Apply the relevant robots groups, including '*' and '$' path patterns.

    ``urllib.robotparser`` treats a rule such as ``Disallow: */job/`` as a
    literal prefix and allows the path. Boards use this pattern to disallow
    listing bodies, so apply the wildcard operators explicitly here.
    """
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []

    def finish_group() -> None:
        nonlocal agents, rules
        if agents:
            groups.append((agents, rules))
        agents, rules = [], []

    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        directive, value = (part.strip() for part in line.split(":", 1))
        directive = directive.lower()
        if directive == "user-agent":
            if rules:
                finish_group()
            agents.append(value.lower())
        elif directive in {"allow", "disallow"} and agents and value:
            rules.append((directive == "allow", value))
    finish_group()

    product = USER_AGENT.split("/", 1)[0].lower()
    matches: list[tuple[int, list[tuple[bool, str]]]] = []
    for group_agents, group_rules in groups:
        specificity = max(
            (len(agent) for agent in group_agents if agent == "*" or agent in product),
            default=-1,
        )
        if specificity >= 0:
            matches.append((specificity, group_rules))
    if not matches:
        return True

    best_specificity = max(score for score, _ in matches)
    target = urlparse(url).path or "/"
    if urlparse(url).query:
        target += "?" + urlparse(url).query
    applicable: list[tuple[int, bool]] = []
    for score, group_rules in matches:
        if score != best_specificity:
            continue
        for allow, pattern in group_rules:
            end_anchor = pattern.endswith("$")
            pattern = pattern[:-1] if end_anchor else pattern
            expression = "^" + ".*".join(re.escape(part) for part in pattern.split("*"))
            if end_anchor:
                expression += "$"
            if re.search(expression, target):
                applicable.append((len(pattern.replace("*", "")), allow))
    if not applicable:
        return True
    specificity = max(length for length, _ in applicable)
    return any(allow for length, allow in applicable if length == specificity)


def _allowed(url: str) -> bool:
    """robots.txt check; unknown/error policy fetches fail closed.

    Fetched via httpx WITH a timeout — RobotFileParser.read() uses urllib with no
    timeout and hangs forever on hosts that black-hole bot connections.
    """
    try:
        parts = urlparse(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return False
        root = f"{parts.scheme}://{parts.netloc}"
        cached = _robot_cache.get(root)
        if cached and cached[0] > time.monotonic():
            _, body, status = cached
        else:
            body, status = None, None
            try:
                resp = _request_public(f"{root}/robots.txt", purpose="robots", timeout=5)
                status = resp.status_code
                if status == 200:
                    body = resp.text
            except (httpx.HTTPError, httpx.InvalidURL, OSError, TimeoutError, ValueError):
                status = 0
            _robot_cache[root] = (time.monotonic() + ROBOTS_TTL, body, status)
        if status == 404:
            return True
        if status != 200 or body is None:
            return False
        return _robots_can_fetch(body, url)
    except (httpx.HTTPError, httpx.InvalidURL, OSError, TimeoutError, ValueError):
        # A robots lookup that times out or cannot be parsed is not permission
        # to crawl. Fail closed so an outage cannot silently bypass site policy.
        return False


def _get(url: str) -> httpx.Response:
    return _request_public(url, purpose="page")


def _job_postings(html: str, source_url: str) -> list[dict[str, str]]:
    """Read explicit Schema.org JobPosting titles from the fetched page only."""
    soup = BeautifulSoup(html, "html.parser")
    postings: list[dict[str, str]] = []

    def visit(value) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            types = value.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if any(str(kind).rsplit("/", 1)[-1].lower() == "jobposting" for kind in types):
                title = str(value.get("title") or "").strip()
                if title and not any(row["title"] == title for row in postings):
                    postings.append({"title": title[:160], "url": source_url})
            for key, child in value.items():
                if key == "@graph":
                    visit(child)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            visit(json.loads(script.string or script.get_text()))
        except (TypeError, ValueError):
            continue
    return postings[:20]


def check_link_status(url: str) -> bool | None:
    """Check a link without browser impersonation or disallowed page-body GETs.

    None means the status could not be established under the same robots, SSRF,
    and board-conduct rules as production tools.
    """
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if _board_listing_url(current) or not _allowed(current):
                return None
            addresses = _public_addresses(current)
            response = _send_pinned_request("HEAD", current, addresses, TIMEOUT)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    return None
                current = urljoin(str(response.url), location)
                continue
            if response.status_code in {401, 403, 405, 406, 409, 429, 503}:
                return None
            return response.status_code < 400
    except (httpx.HTTPError, httpx.InvalidURL, OSError, TimeoutError, ValueError):
        return None
    return None


def fetch_url(url: str) -> ToolResult:
    """Fetch a page and readability-extract the main text (truncated)."""
    if not _allowed(url):
        return ToolResult(ok=False, reason="blocked by robots.txt")
    try:
        resp = _get(url)
        if resp.is_error:
            return ToolResult(ok=False, reason=f"http {resp.status_code}")
        text = trafilatura.extract(resp.text) or ""
        vacancies = _job_postings(resp.text, str(resp.url))
        return ToolResult(
            ok=True,
            data={
                "url": str(resp.url),
                "text": text[:MAX_CHARS],
                "html_len": len(resp.text),
                "vacancies": vacancies,
                # Whether this page invites applications. It is what lets a
                # generic `info@` count as a lead — see `extract_emails`.
                "hiring_signal": bool(HIRING_INVITATION.search(text)),
            },
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
        for m in re.finditer(r'href=["\']([^"\']+)["\']([^>]*)>([^<]*)', resp.text, re.IGNORECASE):
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
ADZUNA_COUNTRIES = frozenset(
    {
        "at",
        "au",
        "be",
        "br",
        "ca",
        "ch",
        "de",
        "es",
        "fr",
        "gb",
        "in",
        "it",
        "mx",
        "nl",
        "nz",
        "pl",
        "sg",
        "us",
        "za",
    }
)


def _company_name_matches(expected: str, observed: str) -> bool:
    """Conservative employer binding; unknown aliases are intentionally rejected."""
    ignored = {"pty", "ltd", "limited", "inc", "llc", "corp", "company", "co"}
    clean = lambda value: {w for w in re.sub(r"[^a-z0-9]+", " ", value.lower()).split() if w not in ignored}
    wanted, actual = clean(expected), clean(observed)
    return bool(wanted and actual and (wanted <= actual or actual <= wanted))


def search_jobs_adzuna(company: str, role: str, country_code: str | None = None,
                       location_context: str = "") -> ToolResult:
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
            timeout=bounded_timeout(TIMEOUT),
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
                "location_uncertain": True,
            }
            for j in results
            if _company_name_matches(company, str((j.get("company") or {}).get("display_name") or ""))
        ]
        if results and not jobs:
            return ToolResult(ok=False, reason="Adzuna results did not verify the target employer")
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
    re.IGNORECASE,
)

# Seek server-renders its employer pages, so one GET distinguishes a page with
# vacancies from an empty one WITHOUT executing JavaScript. Verified 2026-08-11:
#   Boxtech          -> 515,079 bytes, "No matching search results" x1, jobTitle x0
#   Virtual-IT-Group -> 565,218 bytes, "No matching search results" x0, jobTitle x3
_SEEK_JOB_MARKER = re.compile(r'data-automation="jobTitle"')
_SEEK_EMPTY_MARKER = re.compile(r"No matching search results", re.IGNORECASE)

#: Titles per employer page we bother to read. Deciding "is any of these the
#: role?" needs one hit, not the whole board.
MAX_SEEK_TITLES = 25


def _seek_job_titles(html: str) -> list[str]:
    """Vacancy titles from a Seek employer page, in page order, deduped.

    Parsed rather than regexed: the marker sits on an element whose text may be
    nested (``<a data-automation="jobTitle"><span>…</span></a>``), and a regex
    that assumed otherwise would silently return empty strings — which the role
    gate would read as "couldn't judge" and refuse. Falls back to a regex only
    if the parser itself blows up, and returns [] rather than raising.
    """
    titles: list[str] = []
    seen: set[str] = set()
    try:
        soup = BeautifulSoup(html, "html.parser")
        nodes = soup.select('[data-automation="jobTitle"]')
        raw = [n.get_text(" ", strip=True) for n in nodes]
    except Exception:  # noqa: BLE001 — a parser failure is not a vacancy count
        raw = [
            re.sub(r"<[^>]+>", " ", m)
            for m in re.findall(
                r'data-automation="jobTitle"[^>]*>(.{0,200}?)</', html, re.DOTALL
            )
        ]
    for title in raw:
        title = " ".join((title or "").split())[:120]
        if title and title.lower() not in seen:
            seen.add(title.lower())
            titles.append(title)
        if len(titles) >= MAX_SEEK_TITLES:
            break
    return titles


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
    s = re.sub(r"[^0-9A-Za-z\s-]", "", s)  # keep alphanumerics, space, hyphen
    s = re.sub(r"[\s-]+", "-", s).strip("-")  # runs of space/hyphen -> one hyphen
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

    Returns the vacancy **titles** as well as the count. Titles are what makes the
    link checkable: "3 vacancies" was enough to send a *software developer* search
    to Virtual IT Group, whose three openings were all something else. The caller
    (`role_match.gate_seek`, bound in `orchestrator._dispatch_for`) decides whether
    any of them is the role, and suppresses the link when none is.

    Conduct: titles only — no descriptions, salaries, dates or other listing
    content is read, and nothing here is persisted; the titles live only in the
    tool result for the duration of the run, long enough to answer "is this the
    job?". ``/{slug}-jobs/at-this-company`` carries no ``/job/`` segment and no
    query string, so Seek's robots.txt permits it for our user-agent; `_allowed`
    re-checks that at call time and refuses if it ever changes. Reading a
    listing's body, or fetching a ``/job/`` page, would still breach the rule.
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
                data={
                    "url": str(resp.url),
                    "job_count": jobs,
                    "job_titles": _seek_job_titles(html),
                    "company": company,
                },
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
            timeout=bounded_timeout(TIMEOUT),
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
    """Scrape a contact/about page for emails somebody might read a resume at.

    Three tiers, because "the company has an email address" is not a job lead:

    * `NEVER_EMAIL` mailboxes (`sales@`, `support@`, `billing@` …) are dropped
      here so the model never has the option of reporting one.
    * `RECRUITMENT_EMAIL` mailboxes (`careers@`, `hr@` …) stand on their own.
    * everything else — `info@`, `contact@` — is returned but flagged
      `recruitment: false`; `orchestrator._verify_email` only lets those through
      when the page invited applications.

    `hiring_signal` says whether THIS page carried that invitation, which is how
    a cafe whose only address is `info@` still counts. It is read off the page we
    already fetched, so it costs nothing extra.
    """
    if not _allowed(url):
        return ToolResult(ok=False, reason="blocked by robots.txt")
    try:
        resp = _get(url)
        if resp.is_error:
            return ToolResult(ok=False, reason=f"http {resp.status_code}")
        emails = sorted(set(EMAIL_RE.findall(resp.text)))
        # drop obvious asset false-positives
        emails = [e for e in emails if not e.lower().endswith((".png", ".jpg", ".webp"))]
        emails = [e for e in emails if not NEVER_EMAIL.match(e)]
        emails.sort(key=lambda e: (not RECRUITMENT_EMAIL.match(e), e))
        text = trafilatura.extract(resp.text) or resp.text
        return ToolResult(ok=True, data={
            "url": str(resp.url),
            "emails": emails[:5],
            "recruitment": [e for e in emails[:5] if RECRUITMENT_EMAIL.match(e)],
            "hiring_signal": bool(HIRING_INVITATION.search(text)),
        })
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, reason=f"{type(exc).__name__}: {exc}")
