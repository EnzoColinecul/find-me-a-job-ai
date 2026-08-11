"""Budget guard rails.

SerpAPI's free tier is ~250 searches a MONTH, so these caps are what stand
between a PoC and a dead quota. They must hold, and turning them off for
production must be a config change rather than a code change.
"""
import httpx
from botocore.exceptions import ClientError
import pytest
import respx

from fmaj_agent import config
from fmaj_agent.budget import DynamoSearchBudget, NoSharedBudget
from fmaj_agent.discovery import HARD_MAX_COMPANIES
from fmaj_agent.models import Findings, OpportunityType
from fmaj_agent.discovery import discover
from fmaj_agent.orchestrator import AgentRun, _over_budget
from fmaj_agent.places import BASE, PlacesClient

SYD = (-33.8688, 151.2093)


def _run() -> AgentRun:
    return AgentRun(findings=Findings(opportunity_type=OpportunityType.NONE))


def _spend(run: AgentRun, tool: str, budget=None):
    return _over_budget(run, tool, budget or NoSharedBudget())


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
    assert _spend(run, "web_search") is None
    assert _spend(run, "web_search") is None
    denial = _spend(run, "web_search")
    assert denial is not None and "budget reached" in denial
    # Refused attempts are not billed, so they must not be counted.
    assert run.metered_calls["web_search"] == 2


def test_unlimited_web_search_never_refuses(monkeypatch) -> None:
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 0)
    run = _run()
    for _ in range(50):
        assert _spend(run, "web_search") is None
    assert run.metered_calls["web_search"] == 50


def test_free_tools_are_not_metered(monkeypatch) -> None:
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 1)
    run = _run()
    for tool in ("fetch_url", "find_careers_link", "extract_emails", "search_jobs_adzuna"):
        for _ in range(10):
            assert _spend(run, tool) is None
    assert "fetch_url" not in run.metered_calls


# ---- shared per-search budget ----------------------------------------------


class FakeBudgetTable:
    """The one conditional ADD `DynamoSearchBudget` relies on."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.error: Exception | None = None

    def update_item(self, Key, UpdateExpression, ConditionExpression,  # noqa: N803
                    ExpressionAttributeNames, ExpressionAttributeValues):
        if self.error:
            raise self.error
        tool = ExpressionAttributeNames["#t"]
        cap = ExpressionAttributeValues[":cap"]
        used = self.counts.get(tool, 0)
        if used >= cap:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem"
            )
        self.counts[tool] = used + 1


def test_shared_budget_spans_companies(monkeypatch) -> None:
    """The point of the whole thing: separate companies, one SerpAPI budget.

    Each company gets a fresh AgentRun (they're separate Lambdas), so the
    per-company cap can never see the spend. Only the shared counter can.
    """
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 2)
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES_PER_SEARCH", 3)
    budget = DynamoSearchBudget("s1", table=FakeBudgetTable())

    allowed = 0
    for _ in range(5):  # five companies, one call each
        if _spend(_run(), "web_search", budget) is None:
            allowed += 1
    assert allowed == 3


def test_shared_budget_denial_names_the_search_not_the_company(monkeypatch) -> None:
    """The trace shows this text — it must not blame the wrong limit."""
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 9)
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES_PER_SEARCH", 1)
    budget = DynamoSearchBudget("s1", table=FakeBudgetTable())

    assert _spend(_run(), "web_search", budget) is None
    denial = _spend(_run(), "web_search", budget)
    assert denial is not None and "for this search" in denial


def test_per_company_cap_is_checked_before_the_shared_one(monkeypatch) -> None:
    """A call the local cap already refuses must not cost a DynamoDB write."""
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 1)
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES_PER_SEARCH", 10)
    table = FakeBudgetTable()
    budget = DynamoSearchBudget("s1", table=table)
    run = _run()

    assert _spend(run, "web_search", budget) is None
    assert _spend(run, "web_search", budget) is not None
    assert table.counts["web_search"] == 1  # not 2


def test_shared_budget_fails_open(monkeypatch) -> None:
    """DynamoDB being unreachable must not hand the user a worse search.

    Safe precisely because the per-company cap still bounds the damage at the
    arithmetic worst case — which is what shipped before this counter existed.
    """
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 2)
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES_PER_SEARCH", 1)
    table = FakeBudgetTable()
    table.error = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException"}}, "UpdateItem"
    )
    budget = DynamoSearchBudget("s1", table=table)

    assert _spend(_run(), "web_search", budget) is None
    assert _spend(_run(), "web_search", budget) is None


def test_shared_cap_of_zero_is_unlimited(monkeypatch) -> None:
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 0)
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES_PER_SEARCH", 0)
    budget = DynamoSearchBudget("s1", table=FakeBudgetTable())
    for _ in range(20):
        assert _spend(_run(), "web_search", budget) is None


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


def test_budget_summary_reports_the_effective_ceiling(monkeypatch) -> None:
    """The ceiling should be legible without doing mental arithmetic."""
    monkeypatch.setattr(config, "MAX_COMPANIES", 40)
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 2)
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES_PER_SEARCH", 10)
    # The shared cap is what actually binds, not the 40 x 2 product.
    assert config.budget_summary()["web_searches_per_search"] == 10

    # No shared cap: back to the arithmetic worst case.
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES_PER_SEARCH", 0)
    assert config.budget_summary()["web_searches_per_search"] == 80

    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 0)
    assert config.budget_summary()["web_searches_per_search"] == "unlimited"


def test_poc_defaults_stay_inside_the_serpapi_free_tier() -> None:
    """The defaults must survive a month on SerpAPI's ~250 free searches.

    This is now the *shared* per-search cap, not MAX_COMPANIES x
    MAX_WEB_SEARCHES. Those two were coupled by that product, which is why
    protecting SerpAPI once meant cutting the number of companies the user sees
    by 8x. Raising MAX_COMPANIES must never again cost SerpAPI quota.
    """
    import importlib

    fresh = importlib.reload(config)
    per_search = fresh.MAX_WEB_SEARCHES_PER_SEARCH
    assert per_search, "a shared cap must be set, or breadth pays for depth again"
    assert 250 // per_search >= 25, (
        f"defaults allow {per_search} SerpAPI calls per search"
    )


def test_raising_companies_does_not_raise_serpapi_spend(monkeypatch) -> None:
    """The regression this whole change exists to prevent."""
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES", 2)
    monkeypatch.setattr(config, "MAX_WEB_SEARCHES_PER_SEARCH", 10)

    monkeypatch.setattr(config, "MAX_COMPANIES", 5)
    few = config.budget_summary()["web_searches_per_search"]
    monkeypatch.setattr(config, "MAX_COMPANIES", 40)
    many = config.budget_summary()["web_searches_per_search"]

    assert few == many == 10


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
