"""Budget guard rails.

SerpAPI's free tier is ~250 searches a MONTH, so these caps are what stand
between a PoC and a dead quota. They must hold, and turning them off for
production must be a config change rather than a code change.
"""
import httpx
import pytest
import respx

from fmaj_agent import config
from fmaj_agent.discovery import HARD_MAX_COMPANIES
from fmaj_agent.models import Findings, OpportunityType
from fmaj_agent.discovery import discover
from fmaj_agent.orchestrator import AgentRun, _over_budget
from fmaj_agent.places import BASE, PlacesClient

SYD = (-33.8688, 151.2093)


def _run() -> AgentRun:
    return AgentRun(findings=Findings(opportunity_type=OpportunityType.NONE))


def test_zero_means_unlimited() -> None:
    """0 is how production lifts a PoC guard rail without touching code."""
    assert config._limit("FMAJ_NOPE_UNSET", 5) == 5
    monkey = pytest.MonkeyPatch()
    monkey.setenv("FMAJ_NOPE_UNSET", "0")
    assert config._limit("FMAJ_NOPE_UNSET", 5) == 0
    monkey.undo()


def test_garbage_env_falls_back_to_the_default() -> None:
    """A typo in an env var must not silently mean 'unlimited'."""
    monkey = pytest.MonkeyPatch()
    monkey.setenv("FMAJ_NOPE_BAD", "lots")
    assert config._limit("FMAJ_NOPE_BAD", 5) == 5
    monkey.undo()


def test_negative_is_clamped_not_treated_as_unlimited() -> None:
    monkey = pytest.MonkeyPatch()
    monkey.setenv("FMAJ_NOPE_NEG", "-3")
    assert config._limit("FMAJ_NOPE_NEG", 5) == 0
    monkey.undo()


def test_web_search_is_refused_past_the_cap(monkeypatch) -> None:
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 2)
    run = _run()
    assert _over_budget(run, "web_search") is None
    assert _over_budget(run, "web_search") is None
    denial = _over_budget(run, "web_search")
    assert denial is not None and "budget reached" in denial
    # Refused attempts are not billed, so they must not be counted.
    assert run.metered_calls["web_search"] == 2


def test_unlimited_web_search_never_refuses(monkeypatch) -> None:
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 0)
    run = _run()
    for _ in range(50):
        assert _over_budget(run, "web_search") is None
    assert run.metered_calls["web_search"] == 50


def test_free_tools_are_not_metered(monkeypatch) -> None:
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 1)
    run = _run()
    for tool in ("fetch_url", "find_careers_link", "extract_emails", "search_jobs_adzuna"):
        for _ in range(10):
            assert _over_budget(run, tool) is None
    assert "fetch_url" not in run.metered_calls


@respx.mock
def test_discovery_shortlists_only_the_configured_number(monkeypatch) -> None:
    """The cap must bite on the real path: Place Details is the Enterprise SKU,
    so every company past the cap is money we didn't mean to spend."""
    monkeypatch.setattr(config, "MAX_COMPANIES", 3)

    respx.post(f"{BASE}/places:searchNearby").mock(
        return_value=httpx.Response(200, json={"places": [
            {
                "id": f"p{i}",
                "displayName": {"text": f"Cafe {i}"},
                "formattedAddress": "Somewhere St, Sydney NSW",
                # each one slightly further out, so ranking is deterministic
                "location": {"latitude": SYD[0] + i * 0.001, "longitude": SYD[1]},
                "types": ["restaurant"],
            }
            for i in range(10)
        ]}),
    )
    details = respx.get(url__regex=rf"{BASE}/places/.*").mock(
        return_value=httpx.Response(200, json={"websiteUri": "https://x.au"})
    )

    result = discover(*SYD, radius_km=5, roles=["chef"],
                      client=PlacesClient(api_key="test-key"))

    assert len(result.companies) == 3
    # And we only paid for details on the shortlist, not all ten.
    assert details.call_count == 3


def test_unlimited_companies_still_respects_the_hard_ceiling(monkeypatch) -> None:
    """FMAJ_MAX_COMPANIES=0 means 'no PoC limit', not 'no limit at all' —
    Place Details is the Enterprise SKU and one search must not eat the month."""
    monkeypatch.setattr(config, "MAX_COMPANIES", 0)
    resolved = min(config.MAX_COMPANIES or HARD_MAX_COMPANIES, HARD_MAX_COMPANIES)
    assert resolved == HARD_MAX_COMPANIES


def test_budget_summary_states_the_worst_case(monkeypatch) -> None:
    """The ceiling should be legible without doing mental arithmetic."""
    monkeypatch.setattr(config, "MAX_COMPANIES", 5)
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 2)
    assert config.budget_summary()["worst_case_web_searches_per_search"] == 10

    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 0)
    assert config.budget_summary()["worst_case_web_searches_per_search"] == "unlimited"


def test_poc_defaults_stay_inside_the_serpapi_free_tier() -> None:
    """5 x 2 = 10 calls per search -> ~25 searches within 250/month.

    If someone raises these defaults, this test should make them think about the
    monthly quota rather than discovering it when searches start failing.
    """
    import importlib

    fresh = importlib.reload(config)
    ceiling = fresh.MAX_COMPANIES * fresh.MAX_WEB_SEARCHES
    assert ceiling <= 10, f"defaults allow {ceiling} SerpAPI calls per search"
    assert 250 // ceiling >= 25


# ---- key-confusion diagnostics ---------------------------------------------


def test_referrer_blocked_403_explains_the_two_key_rule() -> None:
    """This exact 403 cost a debugging session: the raw Google body buries the
    reason under 500 characters of JSON. The message must name the fix."""
    import httpx

    from fmaj_agent.places import PlacesError, _check

    body = (
        '{"error":{"code":403,"message":"Requests from referer <empty> are '
        'blocked.","status":"PERMISSION_DENIED","details":[{"reason":'
        '"API_KEY_HTTP_REFERRER_BLOCKED"}]}}'
    )
    resp = httpx.Response(
        403, text=body, request=httpx.Request("POST", "https://places.googleapis.com/v1/x")
    )
    with pytest.raises(PlacesError) as exc:
        _check(resp)

    message = str(exc.value)
    assert "SERVER key" in message
    assert "store-external-secrets" in message


def test_other_places_errors_still_show_the_raw_body() -> None:
    """Don't swallow unfamiliar failures behind a friendly guess."""
    import httpx

    from fmaj_agent.places import PlacesError, _check

    resp = httpx.Response(
        500, text="upstream exploded",
        request=httpx.Request("POST", "https://places.googleapis.com/v1/x"),
    )
    with pytest.raises(PlacesError, match="upstream exploded"):
        _check(resp)
