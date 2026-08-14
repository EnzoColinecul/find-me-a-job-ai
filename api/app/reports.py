"""Phase 4 — the downloadable PDF report.

Generated on demand: `GET /searches/{id}/report` renders the search's stored
results into a PDF, caches it in the reports S3 bucket, and hands back a
presigned URL. The report is a *snapshot*, so it is only ever built for a search
that has reached a terminal status — a running search would produce a PDF that
disagrees with the page a poll later.

Why fpdf2 and not WeasyPrint (which PLAN.md sketched): WeasyPrint's Pango/Cairo
native stack is painful to ship in Lambda and to run locally. fpdf2 is pure
Python, so the report renders identically in `uvicorn` dev and in the Mangum
Lambda with no system libraries. It doesn't reproduce the web CSS pixel-for-pixel;
it reuses the palette and the same content model instead.

The link classifier here is a deliberate port of `web/src/lib/links.ts`. The two
must agree — a "Live listing" badge in the PDF has to mean what it means on the
results page — so the patterns and the conservative fall-through to a generic
"Link" are copied, not reinvented. If the web classifier changes, change this too
(a test pins a couple of shared cases).
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import boto3
from fpdf import FPDF

from app.searches import get_search
from app.settings import settings

logger = logging.getLogger(__name__)

# ── palette (design/DESIGN-SPEC.md), as RGB ──────────────────────────────────
INK = (20, 33, 61)         # #14213d navy — primary text
ACCENT = (61, 111, 181)    # #3d6fb5 blue — links, section rules
PIN = (255, 90, 69)        # #ff5a45 — the "worth contacting" count
MUTED = (122, 116, 100)    # a readable relative of ink-muted #8b8574 (body-safe)
FAINT = (150, 145, 130)    # decorative labels only
LINE = (223, 219, 210)     # hairline separators
SURFACE = (255, 253, 247)  # #fffdf7 card fill

# Web parity: results are grouped in this order with these headings
# (web/src/components/results/ResultsPanel.tsx GROUPS).
GROUPS: list[tuple[str, str]] = [
    ("job_listing", "Jobs found"),
    ("careers_page", "Careers pages"),
    ("contact_email", "Worth emailing"),
]
_KNOWN = {t for t, _ in GROUPS}


# ── link classification (port of web/src/lib/links.ts) ───────────────────────
KIND_LABELS: dict[str, str] = {
    "live_listing": "Live listing",
    "employer_listings": "Employer listings",
    "careers_page": "Careers page",
    "company_profile": "Company profile",
    "board_search": "Job board search",
    "community_post": "Community post",
    "other": "Link",
}

# Most useful first: something you can apply to, then the company's own page.
_ORDER = [
    "live_listing",
    "employer_listings",
    "careers_page",
    "company_profile",
    "board_search",
    "community_post",
    "other",
]


def _classify_kind(host: str, path: str) -> str:
    p = path.lower()
    if "facebook." in host or "gumtree." in host:
        return "community_post"
    if "seek.com" in host:
        if p.startswith("/companies/"):
            return "company_profile"
        if _re_job(p):
            return "live_listing"
        if p.rstrip("/").endswith("-jobs/at-this-company") or p.rstrip(
            "/"
        ).endswith("at-this-company"):
            return "employer_listings"
        return "board_search"
    if "linkedin." in host:
        if p.startswith("/jobs/view/"):
            return "live_listing"
        if p.startswith("/company/"):
            return "company_profile"
        return "board_search"
    if "indeed." in host:
        if p.startswith("/cmp/"):
            return "company_profile"
        if p.startswith("/viewjob") or p.startswith("/rc/clk"):
            return "live_listing"
        return "board_search"
    if "adzuna." in host:
        return "live_listing" if "/details/" in p else "board_search"
    if "jora." in host or "careerone." in host:
        return "board_search"
    # A careers-ish path on any normal site → careers page. Conservative
    # elsewhere: an overclaimed badge is worse than a generic one.
    for kw in ("career", "jobs", "vacanc", "work-with-us", "employment",
               "join-us", "hiring"):
        if kw in p:
            return "careers_page"
    return "other"


def _re_job(path: str) -> bool:
    """True for a real Seek vacancy path: /job/<digits>."""
    seg = path.lstrip("/").split("/")
    return len(seg) >= 2 and seg[0] == "job" and seg[1][:1].isdigit()


def _display(host: str, path: str) -> str:
    clean = path.rstrip("/")
    full = f"{host}{clean}"
    if len(full) <= 52:
        return full
    tail = [s for s in clean.split("/") if s]
    last = tail[-1] if tail else ""
    short = (last[:27] + "…") if len(last) > 28 else last
    return f"{host}/…/{short}"


def classify_link(url: str) -> dict:
    """{'url','kind','label','display','note'} — mirrors the web classifier."""
    try:
        u = urlparse(url)
        host = (u.hostname or "").removeprefix("www.")
        path = u.path or ""
    except ValueError:
        return {"url": url, "kind": "other", "label": KIND_LABELS["other"],
                "display": url, "note": ""}
    if not host:
        return {"url": url, "kind": "other", "label": KIND_LABELS["other"],
                "display": url, "note": ""}
    kind = _classify_kind(host, path)
    return {
        "url": url,
        "kind": kind,
        "label": KIND_LABELS[kind],
        "display": _display(host, path),
        "note": "Informal — may expire" if kind == "community_post" else "",
    }


def classify_links(urls: list[str]) -> list[dict]:
    return sorted((classify_link(u) for u in urls),
                  key=lambda c: _ORDER.index(c["kind"]))


# ── text sanitising ──────────────────────────────────────────────────────────
_SUBST = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", " ": " ",
    "•": "-", "‑": "-",
}


def _t(s: str) -> str:
    """Make text safe for fpdf2's latin-1 core fonts without shipping a TTF.

    Common typographic punctuation is transliterated; anything still outside
    latin-1 is dropped rather than crashing the render. Company and place names
    are almost always latin-1 already, so this rarely changes anything visible.
    """
    for bad, good in _SUBST.items():
        s = s.replace(bad, good)
    return s.encode("latin-1", "replace").decode("latin-1")


# ── PDF rendering ────────────────────────────────────────────────────────────
def _grouped(results: list[dict]) -> list[tuple[str, list[dict]]]:
    found = [r for r in results if r.get("opportunity_type") in _KNOWN]
    return [
        (label, [r for r in found if r.get("opportunity_type") == t])
        for t, label in GROUPS
    ]


class _Report(FPDF):
    def footer(self) -> None:  # noqa: D401 — fpdf2 hook
        self.set_y(-14)
        self.set_draw_color(*LINE)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_y(-11)
        self.set_font("Helvetica", size=7.5)
        self.set_text_color(*FAINT)
        self.cell(0, 6, _t("Find Me A Job AI  ·  links open in your browser"),
                  align="L")
        self.cell(0, 6, _t(f"Page {self.page_no()}"), align="R")


def _params_line(params: dict, count: int) -> str:
    bits: list[str] = []
    loc = params.get("location_label") or ""
    if loc:
        bits.append(loc)
    radius = params.get("radius_km")
    if radius:
        bits.append(f"within {radius:g} km")
    roles = [r for r in params.get("roles", []) if r]
    if roles:
        bits.append("for " + ", ".join(roles))
    return "  ·  ".join(bits)


def _title_block(pdf: _Report, search: dict) -> None:
    params = search.get("params", {})
    results = search.get("results", [])
    count = sum(1 for r in results if r.get("opportunity_type") in _KNOWN)

    # brand wordmark + date row
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, _t("Find Me A Job AI"), align="L")
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(*MUTED)
    when = datetime.now(timezone.utc).strftime("%d %b %Y")
    pdf.cell(0, 6, _t(when), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # headline — matches the results page copy
    pdf.set_font("Helvetica", "B", 20)
    if count:
        pdf.set_text_color(*INK)
        head = f"{count} place{'s' if count != 1 else ''} worth contacting"
    else:
        pdf.set_text_color(*INK)
        head = "No opportunities found nearby"
    pdf.multi_cell(0, 9, _t(head), new_x="LMARGIN", new_y="NEXT")

    sub = _params_line(params, count)
    if sub:
        pdf.ln(1)
        pdf.set_font("Helvetica", size=10)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(0, 5.5, _t(sub), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_draw_color(*INK)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(5)


def _section_header(pdf: _Report, label: str) -> None:
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 5, _t(label.upper()), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)


def _badge(pdf: _Report, label: str) -> None:
    """A small filled pill naming a link's kind, then a newline is NOT emitted."""
    pdf.set_font("Helvetica", "B", 7.5)
    w = pdf.get_string_width(label) + 4
    pdf.set_fill_color(233, 238, 246)      # pale accent tint
    pdf.set_text_color(*ACCENT)
    pdf.cell(w, 4.6, _t(label), align="C", fill=True)
    pdf.cell(2, 4.6, "")  # gap


def _company_card(pdf: _Report, n: int, r: dict) -> None:
    left = pdf.l_margin
    inner = left + 9  # text starts to the right of the number badge
    right = pdf.w - pdf.r_margin

    # keep a card from splitting awkwardly right at the page foot
    if pdf.get_y() > pdf.h - 45:
        pdf.add_page()

    top = pdf.get_y()

    # number badge
    pdf.set_fill_color(*INK)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(left, top)
    pdf.cell(6.5, 6.5, str(n), align="C", fill=True)

    # company name
    pdf.set_xy(inner, top)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*INK)
    pdf.set_x(inner)
    pdf.multi_cell(right - inner, 6, _t(r.get("company", "") or "Unnamed business"),
                   new_x="LMARGIN", new_y="NEXT")

    address = r.get("address", "") or ""
    if address:
        pdf.set_x(inner)
        pdf.set_font("Helvetica", size=9)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(right - inner, 4.6, _t(address),
                       new_x="LMARGIN", new_y="NEXT")

    evidence = r.get("evidence", "") or ""
    if evidence:
        pdf.ln(0.8)
        pdf.set_x(inner)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*INK)
        pdf.multi_cell(right - inner, 4.8, _t(evidence),
                       new_x="LMARGIN", new_y="NEXT")

    # links, each with a source badge
    links = classify_links([u for u in r.get("links", []) if u])
    if links:
        pdf.ln(1.2)
    for link in links:
        pdf.set_x(inner)
        _badge(pdf, link["label"])
        pdf.set_font("Helvetica", size=9)
        pdf.set_text_color(*ACCENT)
        text = link["display"]
        if link["note"]:
            text = f"{text}  ({link['note']})"
        pdf.multi_cell(right - pdf.get_x(), 4.6, _t(text),
                       new_x="LMARGIN", new_y="NEXT", link=link["url"])

    emails = [e for e in r.get("emails", []) if e]
    if emails:
        pdf.ln(0.8)
        pdf.set_x(inner)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*INK)
        pdf.cell(pdf.get_string_width("Email  ") , 4.6, _t("Email"))
        pdf.set_font("Helvetica", size=9)
        pdf.set_text_color(*ACCENT)
        pdf.multi_cell(right - pdf.get_x(), 4.6, _t(", ".join(emails)),
                       new_x="LMARGIN", new_y="NEXT",
                       link=f"mailto:{emails[0]}")

    pdf.ln(3.5)
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.2)
    pdf.line(inner, pdf.get_y(), right, pdf.get_y())
    pdf.ln(3.5)


def _empty_state(pdf: _Report) -> None:
    pdf.ln(4)
    pdf.set_font("Helvetica", size=11)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        0, 6,
        _t("The agent checked the businesses nearby but didn't find a careers "
           "page, live listing, or contact worth surfacing for this search. "
           "Try widening the radius or rephrasing the role."),
        new_x="LMARGIN", new_y="NEXT",
    )


def build_pdf(search: dict) -> bytes:
    """Render a search dict (as returned by get_search) into PDF bytes."""
    pdf = _Report(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 15, 18)
    pdf.set_title(_t("Find Me A Job AI — job search report"))
    pdf.add_page()
    _title_block(pdf, search)

    groups = _grouped(search.get("results", []))
    if not any(items for _, items in groups):
        _empty_state(pdf)
    else:
        n = 0
        for label, items in groups:
            if not items:
                continue
            _section_header(pdf, label)
            for r in items:
                n += 1
                _company_card(pdf, n, r)

    out = pdf.output()
    return bytes(out)


# ── S3 storage + presigning ──────────────────────────────────────────────────
_TERMINAL = frozenset({"completed", "cancelled"})
_PRESIGN_TTL = 3600  # 1 hour is plenty for a click-through download

_s3 = None


def _get_s3():
    global _s3
    if _s3 is None:
        session = boto3.Session(
            profile_name=settings.aws_profile or None,
            region_name=settings.aws_region,
        )
        _s3 = session.client("s3")
    return _s3


class ReportNotReady(Exception):
    """The search hasn't reached a terminal status, so there's nothing to report."""


def _key(search_id: str) -> str:
    return f"reports/{search_id}.pdf"


def get_report_url(sub: str, search_id: str) -> dict | None:
    """Presigned URL for the search's PDF report, generating+caching it first.

    Returns None if the search doesn't exist or isn't the caller's — same shape
    as get_search, so the route can 404 uniformly. Raises ReportNotReady if the
    search is still running (or failed): a report is a snapshot of a finished
    search, never a moving target.

    The object is cached under reports/<id>.pdf. A terminal search's results are
    immutable, so a cache hit is always correct and repeat downloads cost only a
    presign, not a re-render.
    """
    search = get_search(sub, search_id)
    if search is None:
        return None
    if search["status"] not in _TERMINAL:
        raise ReportNotReady(search["status"])

    s3 = _get_s3()
    bucket = settings.reports_bucket
    key = _key(search_id)

    try:
        s3.head_object(Bucket=bucket, Key=key)
    except Exception:  # noqa: BLE001 — any miss/error → (re)generate
        try:
            pdf = build_pdf(search)
            s3.upload_fileobj(
                io.BytesIO(pdf), bucket, key,
                ExtraArgs={"ContentType": "application/pdf"},
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to build/upload report for %s", search_id)
            raise

    filename = f"find-me-a-job-{search_id}.pdf"
    url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=_PRESIGN_TTL,
    )
    return {"url": url, "expires_in": _PRESIGN_TTL}
