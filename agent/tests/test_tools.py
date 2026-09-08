"""Tool tests with mocked HTTP (respx). Tools must never raise."""
import httpx
import respx

from fmaj_agent.tools import impl


@respx.mock
def test_fetch_url_extracts_text() -> None:
    respx.get("https://robots.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://robots.example/").mock(
        return_value=httpx.Response(
            200, html="<html><body><article>We are hiring chefs.</article></body></html>"
        )
    )
    r = impl.fetch_url("https://robots.example/")
    assert r.ok
    assert "hiring" in r.data["text"].lower()


@respx.mock
def test_fetch_url_http_error_is_not_raised() -> None:
    respx.get("https://err.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://err.example/").mock(return_value=httpx.Response(500))
    r = impl.fetch_url("https://err.example/")
    assert not r.ok and "500" in r.reason


@respx.mock
def test_find_careers_link() -> None:
    respx.get("https://co.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://co.example/").mock(
        return_value=httpx.Response(
            200,
            html=(
                '<a href="/about">About</a>'
                '<a href="/careers">Join our team</a>'
                '<a href="https://co.example/jobs">Jobs</a>'
            ),
        )
    )
    r = impl.find_careers_link("https://co.example/")
    assert r.ok
    cands = r.data["candidates"]
    assert any(c.endswith("/careers") for c in cands)
    assert any(c.endswith("/jobs") for c in cands)
    assert not any(c.endswith("/about") for c in cands)


@respx.mock
def test_extract_emails_prefers_careers() -> None:
    respx.get("https://mail.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://mail.example/contact").mock(
        return_value=httpx.Response(
            200, html="Reach us at info@mail.example or careers@mail.example"
        )
    )
    r = impl.extract_emails("https://mail.example/contact")
    assert r.ok
    assert r.data["emails"][0] == "careers@mail.example"  # preferred first
    assert r.data["recruitment"] == ["careers@mail.example"]


@respx.mock
def test_adzuna_parses_results(monkeypatch) -> None:
    monkeypatch.setenv("FMAJ_ADZUNA_APP_ID", "id")
    monkeypatch.setenv("FMAJ_ADZUNA_APP_KEY", "key")
    respx.get(url__startswith="https://api.adzuna.com/v1/api/jobs/au/search/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Chef",
                        "company": {"display_name": "Cafe X"},
                        "location": {"display_name": "Sydney"},
                        "redirect_url": "https://adzuna/job/1",
                    }
                ]
            },
        )
    )
    r = impl.search_jobs_adzuna("Cafe X", "chef", country_code="au")
    assert r.ok and r.data["jobs"][0]["title"] == "Chef"


@respx.mock
def test_adzuna_queries_the_company_s_own_country(monkeypatch) -> None:
    """The country comes from Places, not from a hardcoded `au` in the URL."""
    monkeypatch.setenv("FMAJ_ADZUNA_APP_ID", "id")
    monkeypatch.setenv("FMAJ_ADZUNA_APP_KEY", "key")
    route = respx.get(
        url__startswith="https://api.adzuna.com/v1/api/jobs/gb/search/1"
    ).mock(return_value=httpx.Response(200, json={"results": []}))

    r = impl.search_jobs_adzuna("Cafe X", "chef", country_code="GB")

    assert r.ok and route.called


def test_adzuna_refuses_a_country_it_does_not_index() -> None:
    """Better a readable refusal than a 404 the model has to interpret."""
    r = impl.search_jobs_adzuna("Cafe X", "chef", country_code="jp")
    assert not r.ok and "JP" in r.reason


def test_adzuna_refuses_when_the_country_is_unknown() -> None:
    """Unknown must never fall back to Australia — that was the original bug."""
    r = impl.search_jobs_adzuna("Cafe X", "chef", country_code=None)
    assert not r.ok and "country" in r.reason.lower()


def test_seek_is_skipped_outside_australia() -> None:
    """Seek has no employer pages abroad, so don't spend a tool call finding out."""
    r = impl.find_seek_company_page("Cafe X", country_code="us")
    assert not r.ok and "Australia" in r.reason

    r = impl.find_seek_company_page("Cafe X", country_code=None)
    assert not r.ok and "Australia" in r.reason


@respx.mock
def test_web_search_returns_links(monkeypatch) -> None:
    monkeypatch.setenv("FMAJ_SERPAPI_KEY", "k")
    respx.get(url__startswith="https://serpapi.com/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "organic_results": [
                    {"title": "Cafe X jobs", "link": "https://seek.com.au/cafe-x", "snippet": "…"}
                ]
            },
        )
    )
    r = impl.web_search('site:seek.com.au "Cafe X"')
    assert r.ok and r.data["results"][0]["link"].startswith("https://seek")


def test_seek_company_slug_formats() -> None:
    assert impl._seek_company_slug("Virtual IT Group") == "Virtual-IT-Group"
    assert impl._seek_company_slug("Elegant Media") == "Elegant-Media"
    assert impl._seek_company_slug("Springtek") == "Springtek"
    assert impl._seek_company_slug("Ben & Jerry's") == "Ben-and-Jerrys"
    assert impl._seek_company_slug("Acme Pty Ltd") == "Acme"
    assert impl._seek_company_slug("  Multiple   Spaces  ") == "Multiple-Spaces"


@respx.mock
def test_seek_company_page_returns_url_when_it_has_vacancies() -> None:
    impl._robot_cache.clear()
    respx.get("https://au.seek.com/robots.txt").mock(return_value=httpx.Response(404))
    url = "https://au.seek.com/Virtual-IT-Group-jobs/at-this-company"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            html='<a data-automation="jobTitle" href="/job/1">A</a>'
                 '<a data-automation="jobTitle" href="/job/2"><span>B</span></a>'
                 '<div data-automation="jobTitle">  C  </div>',
        )
    )
    r = impl.find_seek_company_page("Virtual IT Group", country_code="au")
    assert r.ok
    assert r.data["url"] == url
    assert r.data["job_count"] == 3
    assert r.data["job_titles"] == ["A", "B", "C"]


@respx.mock
def test_seek_company_page_with_no_results_is_rejected() -> None:
    """The reported bug: Seek serves 200 + an empty page for an unknown employer.

    Observed 2026-08-11 for `Boxtech` — 515KB of HTML, zero job markers. A link to
    this must never reach the user.
    """
    impl._robot_cache.clear()
    respx.get("https://au.seek.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://au.seek.com/Boxtech-jobs/at-this-company").mock(
        return_value=httpx.Response(
            200, html="<h1>No matching search results</h1>" + "<div>filler</div>" * 500
        )
    )
    r = impl.find_seek_company_page("Boxtech", country_code="au")
    assert not r.ok
    assert "no current listings" in r.reason


@respx.mock
def test_seek_company_page_fails_closed_when_markers_are_missing() -> None:
    """Unrecognised markup must not be read as 'has vacancies'."""
    impl._robot_cache.clear()
    respx.get("https://au.seek.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://au.seek.com/Redesigned-Co-jobs/at-this-company").mock(
        return_value=httpx.Response(200, html="<main>totally new markup</main>")
    )
    r = impl.find_seek_company_page("Redesigned Co", country_code="au")
    assert not r.ok
    assert "could not confirm" in r.reason


@respx.mock
def test_seek_company_page_404_is_not_raised() -> None:
    impl._robot_cache.clear()
    respx.get("https://au.seek.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://au.seek.com/Ghost-Co-jobs/at-this-company").mock(
        return_value=httpx.Response(404)
    )
    r = impl.find_seek_company_page("Ghost Co", country_code="au")
    assert not r.ok and "404" in r.reason


@respx.mock
def test_seek_company_page_respects_robots() -> None:
    """If Seek ever disallows the employer path, the tool must refuse."""
    impl._robot_cache.clear()
    respx.get("https://au.seek.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /\n")
    )
    r = impl.find_seek_company_page("Virtual IT Group", country_code="au")
    assert not r.ok
    assert "robots" in r.reason


@respx.mock
def test_seek_job_titles_are_read_for_the_role_check() -> None:
    """"3 vacancies" sent a software-developer search to Virtual IT Group whose
    three vacancies were all other jobs. The titles are what makes it checkable.
    """
    impl._robot_cache.clear()
    respx.get("https://au.seek.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://au.seek.com/Virtual-IT-Group-jobs/at-this-company").mock(
        return_value=httpx.Response(200, html=(
            '<a data-automation="jobTitle"><span>Service Desk</span> Analyst</a>'
            '<a data-automation="jobTitle">Business Development Manager</a>'
            '<a data-automation="jobTitle">Business Development Manager</a>'
        ))
    )
    r = impl.find_seek_company_page("Virtual IT Group", country_code="au")
    assert r.ok
    # nested markup is flattened, whitespace collapsed, duplicates dropped
    assert r.data["job_titles"] == ["Service Desk Analyst", "Business Development Manager"]
    assert r.data["job_count"] == 3  # the raw marker count is still the honest total


def test_seek_titles_survive_unparseable_html() -> None:
    """A parser failure must not read as "no vacancies" — that fails the wrong way."""
    html = '<a data-automation="jobTitle">Sous Chef</a'  # truncated on purpose
    assert impl._seek_job_titles(html) == ["Sous Chef"]
    assert impl._seek_job_titles("") == []


@respx.mock
def test_extract_emails_drops_mailboxes_nobody_reads_resumes_at() -> None:
    """The reported case: `sales@trendzit.com.au` offered as a way into a company."""
    impl._robot_cache.clear()
    respx.get("https://trendz.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://trendz.example/contact").mock(
        return_value=httpx.Response(200, html=(
            "Sales: sales@trendz.example · Support: support@trendz.example · "
            "Billing: accounts@trendz.example · noreply@trendz.example"
        ))
    )
    r = impl.extract_emails("https://trendz.example/contact")
    assert r.ok
    assert r.data["emails"] == []          # the model never gets the option
    assert r.data["hiring_signal"] is False


@respx.mock
def test_extract_emails_flags_a_page_that_invites_applications() -> None:
    """Starboard IT: a general address, but the About page asks for resumes."""
    impl._robot_cache.clear()
    respx.get("https://star.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://star.example/about").mock(
        return_value=httpx.Response(200, html=(
            "<article><p>We are always keen to meet new talent. If you like the "
            "look of us, please send us your resume — info@star.example</p></article>"
        ))
    )
    r = impl.extract_emails("https://star.example/about")
    assert r.ok
    assert r.data["emails"] == ["info@star.example"]
    assert r.data["recruitment"] == []      # generic mailbox…
    assert r.data["hiring_signal"] is True  # …but the page asked for resumes


def test_hiring_invitation_needs_a_phrase_not_a_keyword() -> None:
    """A "Careers" nav item is not an invitation; "send us your resume" is."""
    match = lambda t: bool(impl.HIRING_INVITATION.search(t))  # noqa: E731
    assert match("please send us your resume")
    assert match("We are currently hiring for several roles")
    assert match("View our current vacancies")
    assert not match("Home | About | Careers | Contact")
    assert not match("Trendz IT Solutions provides managed IT services.")
