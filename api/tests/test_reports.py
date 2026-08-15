"""Phase 4 — PDF report: link classifier parity, PDF rendering, and the route.

The classifier is a port of web/src/lib/links.ts; the parity cases here are the
tripwire for the two drifting apart. The PDF assertions stay at the "it renders
and it's a PDF" level on purpose — pinning exact bytes would break on every
harmless layout tweak.
"""
import app.reports as reports
import pytest
from app.main import app
from app.auth import AuthUser, require_user
from fastapi.testclient import TestClient

client = TestClient(app)


# ── link classifier (must agree with the web) ────────────────────────────────
@pytest.mark.parametrize(
    "url,kind",
    [
        ("https://au.seek.com/job/12345678", "live_listing"),
        ("https://au.seek.com/companies/acme", "company_profile"),
        ("https://au.seek.com/chef-jobs/at-this-company", "employer_listings"),
        ("https://au.seek.com/chef-jobs", "board_search"),
        ("https://www.linkedin.com/jobs/view/999", "live_listing"),
        ("https://www.linkedin.com/company/acme", "company_profile"),
        ("https://au.indeed.com/viewjob?jk=1", "live_listing"),
        ("https://acme.com.au/careers", "careers_page"),
        ("https://facebook.com/acme/posts/1", "community_post"),
        ("https://weird.example/about", "other"),
    ],
)
def test_classifier_matches_web(url: str, kind: str) -> None:
    assert reports.classify_link(url)["kind"] == kind


def test_classifier_orders_most_useful_first() -> None:
    got = reports.classify_links([
        "https://weird.example/x",             # other
        "https://au.seek.com/job/1",           # live_listing
        "https://acme.com.au/careers",         # careers_page
    ])
    assert [c["kind"] for c in got] == ["live_listing", "careers_page", "other"]


def test_display_strips_protocol_and_query() -> None:
    d = reports.classify_link("https://www.acme.com.au/careers?x=1")["display"]
    assert d.startswith("acme.com.au/careers") and "http" not in d


# ── PDF rendering ────────────────────────────────────────────────────────────
def _search(status="completed", results=None):
    return {
        "search_id": "abc123",
        "status": status,
        "params": {
            "lat": -33.88, "lng": 151.21, "radius_km": 5,
            "roles": ["chef"], "location_label": "Surry Hills NSW 2010",
        },
        "results": results if results is not None else [
            {"place_id": "p1", "company": "Café Ora – Bistro",
             "address": "12 Crown St", "opportunity_type": "job_listing",
             "evidence": "Live chef vacancy on Seek.",
             "links": ["https://au.seek.com/job/87654321",
                       "https://cafeora.com.au/careers"],
             "emails": ["jobs@cafeora.com.au"]},
        ],
    }


def test_build_pdf_returns_a_pdf() -> None:
    pdf = reports.build_pdf(_search())
    assert isinstance(pdf, bytes) and pdf[:5] == b"%PDF-"


def test_build_pdf_survives_non_latin1_text() -> None:
    """Smart quotes / dashes / accents must not crash the core-font render."""
    r = _search(results=[
        {"place_id": "p1", "company": "Café “Naïve” — Kööks",
         "address": "1 Résumé St", "opportunity_type": "careers_page",
         "evidence": "They’re hiring — see the page…", "links": [], "emails": []},
    ])
    assert reports.build_pdf(r)[:5] == b"%PDF-"


def test_build_pdf_empty_state() -> None:
    """A completed search with nothing found still produces a valid PDF."""
    r = _search(results=[
        {"place_id": "x", "company": "Nowhere", "opportunity_type": "none",
         "links": [], "emails": []},
    ])
    assert reports.build_pdf(r)[:5] == b"%PDF-"


# ── get_report_url orchestration ─────────────────────────────────────────────
class _FakeS3:
    def __init__(self, exists=False):
        self.exists = exists
        self.uploaded = False

    def head_object(self, Bucket, Key):  # noqa: N803
        if not self.exists:
            raise RuntimeError("404")

    def upload_fileobj(self, fileobj, Bucket, Key, ExtraArgs=None):  # noqa: N803
        self.uploaded = True

    def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: N803
        return f"https://s3.example/{Params['Key']}?sig=1"


def test_report_url_generates_and_presigns(monkeypatch) -> None:
    s3 = _FakeS3(exists=False)
    monkeypatch.setattr(reports, "get_search", lambda sub, sid: _search())
    monkeypatch.setattr(reports, "_get_s3", lambda: s3)
    out = reports.get_report_url("u1", "abc123")
    assert out is not None and out["url"].startswith("https://s3.example/")
    assert s3.uploaded is True  # nothing cached yet → it built + uploaded


def test_report_url_reuses_cached_object(monkeypatch) -> None:
    s3 = _FakeS3(exists=True)
    monkeypatch.setattr(reports, "get_search", lambda sub, sid: _search())
    monkeypatch.setattr(reports, "_get_s3", lambda: s3)
    reports.get_report_url("u1", "abc123")
    assert s3.uploaded is False  # cache hit → re-presign only, no re-render


def test_report_url_none_when_not_owner(monkeypatch) -> None:
    monkeypatch.setattr(reports, "get_search", lambda sub, sid: None)
    assert reports.get_report_url("intruder", "abc123") is None


def test_report_url_raises_when_still_running(monkeypatch) -> None:
    monkeypatch.setattr(reports, "get_search",
                        lambda sub, sid: _search(status="running"))
    with pytest.raises(reports.ReportNotReady):
        reports.get_report_url("u1", "abc123")


def test_report_url_allows_cancelled(monkeypatch) -> None:
    """A cancelled search keeps whatever real results it collected — reportable."""
    s3 = _FakeS3(exists=False)
    monkeypatch.setattr(reports, "get_search",
                        lambda sub, sid: _search(status="cancelled"))
    monkeypatch.setattr(reports, "_get_s3", lambda: s3)
    assert reports.get_report_url("u1", "abc123") is not None


# ── the route ────────────────────────────────────────────────────────────────
def _as_user(sub="u1"):
    app.dependency_overrides[require_user] = lambda: AuthUser(
        sub=sub, email="e@x.com"
    )


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_route_returns_url(monkeypatch) -> None:
    _as_user()
    monkeypatch.setattr("app.reports.get_report_url",
                        lambda sub, sid: {"url": "https://s3.example/r.pdf",
                                          "expires_in": 3600})
    resp = client.get("/searches/abc123/report")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://s3.example/r.pdf"


def test_route_404_when_missing(monkeypatch) -> None:
    _as_user()
    monkeypatch.setattr("app.reports.get_report_url", lambda sub, sid: None)
    resp = client.get("/searches/nope/report")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "not_found"


def test_route_409_when_not_ready(monkeypatch) -> None:
    _as_user()

    def _raise(sub, sid):
        raise reports.ReportNotReady("running")

    monkeypatch.setattr("app.reports.get_report_url", _raise)
    resp = client.get("/searches/abc123/report")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "report_not_ready"


def test_route_requires_auth() -> None:
    resp = client.get("/searches/abc123/report")
    assert resp.status_code == 401
