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
    r = impl.search_jobs_adzuna("Cafe X", "chef")
    assert r.ok and r.data["jobs"][0]["title"] == "Chef"


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
