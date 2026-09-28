"""The backstop: a reported `job_listing` must name a vacancy that is the role.

The per-tool gates in `role_match` catch Seek and Adzuna. This catches everything
else — a listing read out of careers-page text, a board link inferred from a
`web_search` result, or a model that simply asserts one.
"""
import pytest

from fmaj_agent import role_match
from fmaj_agent.models import Findings, OpportunityType
from fmaj_agent.orchestrator import (
    AgentRun, EvidenceRecord, _is_board_link, _verify, _verify_listing,
)

ROLES = ["software developer"]


def _run(observed=None, verified=None) -> AgentRun:
    run = AgentRun(findings=Findings(opportunity_type=OpportunityType.NONE),
                   company_id="test-company")
    run.observed_titles = {t.lower(): t for t in (observed or [])}
    run.verified_titles = {t.lower() for t in (verified or [])}
    run.observed_urls = {
        "https://au.seek.com/Acme-jobs/at-this-company",
        "https://acme.com/careers", "https://acme.com/careers/grad",
        "https://au.seek.com/Virtual-IT-Group-jobs/at-this-company",
        "https://virtualitgroup.com.au/careers",
        "https://au.seek.com/X-jobs/at-this-company",
        "https://www.linkedin.com/jobs/view/123",
    }
    run.evidence_records = [EvidenceRecord(
        company_id=run.company_id, claim_type="url", claim_value=url,
        source_url=url, source_type="test", observed_at=1.0,
    ) for url in run.observed_urls]
    for title in set(observed or []) | set(verified or []):
        run.title_sources[title.lower()] = set(run.observed_urls)
        run.evidence_records.extend(EvidenceRecord(
            company_id=run.company_id, claim_type="vacancy_title",
            claim_value=title.lower(), source_url=url, source_type="test",
            observed_at=1.0,
        ) for url in run.observed_urls)
    return run


def _listing(**kw) -> Findings:
    return Findings(opportunity_type=OpportunityType.JOB_LISTING,
                    evidence="found a role", confidence=0.9, **kw)


@pytest.fixture(autouse=True)
def _no_judge(monkeypatch):
    """Nothing here should need the model — anything that does is a bug."""
    class Never:
        def complete(self, *a, **kw):
            raise AssertionError("the report gate should not re-judge a cleared title")

    monkeypatch.setattr(role_match, "get_provider", lambda: Never())
    role_match._cache.clear()
    yield
    role_match._cache.clear()


def test_a_verified_title_stands() -> None:
    f = _listing(links=["https://au.seek.com/Acme-jobs/at-this-company"],
                 matched_title="Full Stack Engineer")
    out, why = _verify_listing(f, _run(verified=["Full Stack Engineer"]), ROLES)
    assert why == ""
    assert out.opportunity_type is OpportunityType.JOB_LISTING


def test_adzuna_listing_labels_unverified_vacancy_location() -> None:
    run = _run(verified=["Chef"])
    url = "https://adzuna.example/jobs/1"
    run.observed_urls = {url}
    run.title_sources["chef"] = {url}
    run.evidence_records.append(EvidenceRecord(
        company_id=run.company_id, claim_type="vacancy_title", claim_value="chef",
        source_url=url, source_type="search_jobs_adzuna", observed_at=1.0,
    ))
    run.location_uncertain_titles.add("chef")
    finding = _listing(links=[url], matched_title="Chef")
    out, why = _verify_listing(finding, run, ["chef"])
    assert why == ""
    assert "location has not been confirmed" in out.evidence


def test_a_verified_title_cannot_bless_a_different_observed_url() -> None:
    run = _run(verified=["Full Stack Engineer"])
    run.title_sources["full stack engineer"] = {"https://acme.com/careers"}
    finding = _listing(links=["https://au.seek.com/Acme-jobs/at-this-company"],
                       matched_title="Full Stack Engineer")
    out, why = _verify_listing(finding, run, ROLES)
    assert "listing URL that no tool returned" in why
    assert out.opportunity_type is OpportunityType.NONE


def test_evidence_from_another_company_cannot_support_a_listing() -> None:
    run = _run(verified=["Full Stack Engineer"])
    run.evidence_records = [
        record for record in run.evidence_records
        if record.claim_type != "vacancy_title"
    ] + [
        EvidenceRecord(
            company_id="different-company", claim_type="vacancy_title",
            claim_value="full stack engineer",
            source_url="https://au.seek.com/Acme-jobs/at-this-company",
            source_type="find_seek_company_page", observed_at=2.0,
        )
    ]
    finding = _listing(links=["https://au.seek.com/Acme-jobs/at-this-company"],
                       matched_title="Full Stack Engineer")
    out, _ = _verify_listing(finding, run, ROLES)
    assert out.opportunity_type is OpportunityType.NONE


def test_a_listing_with_no_title_is_downgraded() -> None:
    """"I found a listing" is not evidence of one."""
    f = _listing(links=["https://acme.com/careers"])
    out, why = _verify_listing(f, _run(), ROLES)
    assert out.opportunity_type is OpportunityType.CAREERS_PAGE
    assert "without naming the vacancy" in why
    assert out.confidence <= 0.5
    assert "not a matching listing" in out.evidence


def test_an_invented_title_is_downgraded() -> None:
    f = _listing(links=["https://acme.com/careers"], matched_title="Senior Developer")
    out, why = _verify_listing(f, _run(observed=["Service Desk Analyst"]), ROLES)
    assert out.opportunity_type is OpportunityType.CAREERS_PAGE
    assert "no tool returned" in why


def test_a_downgrade_drops_the_board_link_but_keeps_the_company_site() -> None:
    """A Seek link only ever meant "a vacancy is here". Without a matching
    vacancy it says nothing, while the company's own careers page still does."""
    f = _listing(
        links=["https://au.seek.com/Virtual-IT-Group-jobs/at-this-company",
               "https://virtualitgroup.com.au/careers"],
        matched_title="Service Desk Analyst",
    )
    out, _ = _verify_listing(f, _run(verified=[]), ROLES)
    assert out.links == ["https://virtualitgroup.com.au/careers"]
    assert out.opportunity_type is OpportunityType.CAREERS_PAGE


def test_a_downgrade_falls_through_to_an_email() -> None:
    f = _listing(links=["https://au.seek.com/X-jobs/at-this-company"],
                 emails=["careers@intuitionsoftech.com"])
    out, _ = _verify_listing(f, _run(), ROLES)
    assert out.opportunity_type is OpportunityType.CONTACT_EMAIL
    assert out.emails == ["careers@intuitionsoftech.com"]


def test_composed_verify_drops_unobserved_email_after_listing_downgrade() -> None:
    finding = _listing(
        links=["https://au.seek.com/X-jobs/at-this-company"],
        emails=["sales@invented.example"],
        matched_title="Service Desk Analyst",
    )
    out, reason = _verify(finding, _run(), ROLES)
    assert out.opportunity_type is OpportunityType.NONE
    assert out.emails == []
    assert "not read off the company's own page" in reason


def test_cancellation_after_model_turn_blocks_the_next_tool(monkeypatch) -> None:
    from fmaj_agent import orchestrator
    from fmaj_agent.models import Company
    from fmaj_agent.providers import ToolUse, Turn

    stopped = False

    class Provider:
        calls = 0

        def complete(self, *args, **kwargs):
            nonlocal stopped
            self.calls += 1
            if self.calls == 1:
                return Turn(text='{"plausible": true}')
            stopped = True
            return Turn(tool_uses=[ToolUse(
                id="tool-1", name="fetch_url", input={"url": "https://acme.example"}
            )])

    provider = Provider()
    monkeypatch.setattr(orchestrator, "get_provider", lambda: provider)
    monkeypatch.setattr(orchestrator, "fetch_url", lambda _url: pytest.fail("tool ran after stop"))
    run = orchestrator.investigate(
        Company(place_id="p", name="Acme", address="Melbourne", website="https://acme.example",
                roles=["chef"], country_code="au"),
        should_stop=lambda: stopped,
    )
    assert run.cancelled
    assert run.tool_calls == 0


def test_fetching_is_scoped_to_the_company_site_and_its_careers_links(monkeypatch) -> None:
    from fmaj_agent import orchestrator
    from fmaj_agent.models import Company, ToolResult

    called = []

    def careers(url):
        called.append(("careers", url))
        return ToolResult(ok=True, data={"candidates": ["https://jobs.greenhouse.io/acme"]})

    def fetch(url):
        called.append(("fetch", url))
        return ToolResult(ok=True, data={"url": url})

    monkeypatch.setattr(orchestrator, "find_careers_link", careers)
    monkeypatch.setattr(orchestrator, "fetch_url", fetch)
    dispatch = orchestrator._dispatch_for(Company(
        place_id="p", name="Acme", address="Melbourne", website="https://www.acme.example",
        roles=["chef"], country_code="au",
    ))
    dispatch["find_careers_link"]({"url": "https://acme.example"})
    allowed = dispatch["fetch_url"]({"url": "https://jobs.greenhouse.io/acme"})
    blocked = dispatch["fetch_url"]({"url": "https://other-employer.example/careers"})

    assert allowed.ok
    assert not blocked.ok and "not linked" in blocked.reason
    assert called == [
        ("careers", "https://acme.example"),
        ("fetch", "https://jobs.greenhouse.io/acme"),
    ]


def test_a_downgrade_with_nothing_left_drops_the_company() -> None:
    f = _listing(links=["https://www.linkedin.com/jobs/view/123"])
    out, _ = _verify_listing(f, _run(), ROLES)
    assert out.opportunity_type is OpportunityType.NONE
    assert out.links == []


def test_other_opportunity_types_are_untouched() -> None:
    f = Findings(opportunity_type=OpportunityType.CAREERS_PAGE,
                 links=["https://acme.com/careers"], evidence="careers page",
                 confidence=0.8)
    out, why = _verify_listing(f, _run(), ROLES)
    assert why == "" and out is f


def test_board_links_are_recognised() -> None:
    assert _is_board_link("https://au.seek.com/Acme-jobs/at-this-company")
    assert _is_board_link("https://www.linkedin.com/jobs/view/1")
    assert _is_board_link("https://www.adzuna.com.au/details/1")
    assert not _is_board_link("https://virtualitgroup.com.au/careers")
    assert not _is_board_link("not a url")


def test_an_observed_but_unjudged_title_is_judged_now(monkeypatch) -> None:
    """A title read off a careers page was never gated — check it at report time."""
    monkeypatch.setattr(role_match, "match_titles",
                        lambda titles, roles: role_match.MatchReport(
                            matched=[role_match.TitleVerdict(title=titles[0], score=1.0)]))
    run = _run(observed=["Graduate Software Engineer"])
    f = _listing(links=["https://acme.com/careers/grad"],
                 matched_title="Graduate Software Engineer")
    out, why = _verify_listing(f, run, ROLES)
    assert why == "" and out.opportunity_type is OpportunityType.JOB_LISTING
    assert "graduate software engineer" in run.verified_titles


# ── end to end through investigate() ───────────────────────────────────────

def _turn(name=None, **args):
    from fmaj_agent.providers import ToolUse, Turn
    if name is None:
        return Turn(text='{"plausible": true}')
    return Turn(text="", tool_uses=[ToolUse(id="t1", name=name, input=args)])


class ScriptedProvider:
    """Replays a fixed list of turns — the model, with the guessing removed."""

    def __init__(self, turns):
        self.turns = list(turns)

    def complete(self, *a, **kw):
        return self.turns.pop(0)


def test_virtual_it_group_end_to_end(monkeypatch) -> None:
    """The whole reported bug, from Places result to what the user would see.

    Seek says Virtual IT Group has three vacancies; none is a developer job. The
    agent must not come back with a Seek link.
    """
    from fmaj_agent import orchestrator
    from fmaj_agent.models import Company, ToolResult

    monkeypatch.setattr(orchestrator, "find_seek_company_page", lambda *a, **kw: ToolResult(
        ok=True, data={
            "url": "https://au.seek.com/Virtual-IT-Group-jobs/at-this-company",
            "job_count": 3,
            "job_titles": ["Service Desk Analyst", "Business Development Manager",
                           "Account Manager"],
        }))
    monkeypatch.setattr(role_match, "match_titles",
                        lambda titles, roles: role_match.MatchReport(
                            rejected=[role_match.TitleVerdict(title=t) for t in titles]))

    provider = ScriptedProvider([
        _turn(),                                                   # triage
        _turn("find_seek_company_page", company="Virtual IT Group"),
        _turn("report_findings", opportunity_type="job_listing",
              links=["https://au.seek.com/Virtual-IT-Group-jobs/at-this-company"],
              evidence="Seek shows 3 vacancies", confidence=0.9),
    ])
    monkeypatch.setattr(orchestrator, "get_provider", lambda: provider)

    steps = []
    run = orchestrator.investigate(
        Company(place_id="p", name="Virtual IT Group", address="Melbourne VIC",
                roles=["software developer"], country_code="au"),
        on_step=steps.append,
    )

    assert run.findings.opportunity_type is OpportunityType.NONE
    assert run.findings.links == []          # the Seek link never reaches the user
    assert "not a matching listing" in run.findings.evidence
    assert any(s.tool == "role_match" for s in steps)   # and the panel says so


# ── contact_email: an address is not automatically a lead ──────────────────

from fmaj_agent.orchestrator import _verify_email  # noqa: E402


def _email_run(observed=(), hiring=False) -> AgentRun:
    run = _run()
    run.observed_emails = {e.lower(): e for e in observed}
    run.saw_hiring_signal = hiring
    run.observed_email_sources = {
        e.lower(): ("https://company.example/contact", hiring) for e in observed
    }
    run.observed_urls.add("https://company.example/contact")
    run.evidence_records.extend(EvidenceRecord(
        company_id=run.company_id, claim_type="email", claim_value=e.lower(),
        source_url="https://company.example/contact", source_type="extract_emails",
        observed_at=1.0, hiring_signal=hiring,
    ) for e in observed)
    return run


def _email_finding(*emails, links=(), evidence="found an address") -> Findings:
    return Findings(opportunity_type=OpportunityType.CONTACT_EMAIL,
                    emails=list(emails), links=list(links) or ["https://company.example/contact"],
                    evidence=evidence, confidence=0.9)


def test_starboard_it_is_kept() -> None:
    """A mailbox labelled for hiring stands on its own evidence."""
    f = _email_finding("hr@starboardit.com")
    out, why = _verify_email(f, _email_run(["hr@starboardit.com"]))
    assert why == ""
    assert out.opportunity_type is OpportunityType.CONTACT_EMAIL
    assert out.emails == ["hr@starboardit.com"]


def test_trendz_sales_address_is_dropped() -> None:
    """The reported case: a sales inbox, a dead site, nothing inviting anyone."""
    f = _email_finding("sales@trendzit.com.au",
                       evidence="No active job listings or working careers page")
    out, why = _verify_email(f, _email_run(["sales@trendzit.com.au"]))
    assert out.opportunity_type is OpportunityType.NONE
    assert out.emails == []
    assert "not a hiring address" in why
    assert "dropped:" in out.evidence


def test_an_address_from_a_search_snippet_is_dropped() -> None:
    """"Found via official company listings" is not the same as found on their
    site. Same provenance rule the matched_title gate applies to listings."""
    f = _email_finding("careers@trendzit.com.au")   # even a good-looking mailbox
    out, why = _verify_email(f, _email_run(observed=[]))
    assert out.opportunity_type is OpportunityType.NONE
    assert "not read off the company" in why


def test_a_generic_address_survives_a_hiring_invitation() -> None:
    """The cafe case: `info@` is the only address, but the page asks for resumes."""
    f = _email_finding("info@cafe.example")
    out, why = _verify_email(f, _email_run(["info@cafe.example"], hiring=True))
    assert why == "" and out.emails == ["info@cafe.example"]


def test_a_generic_address_alone_is_not_enough() -> None:
    f = _email_finding("info@cafe.example")
    out, _ = _verify_email(f, _email_run(["info@cafe.example"], hiring=False))
    assert out.opportunity_type is OpportunityType.NONE


def test_a_good_address_survives_alongside_a_bad_one() -> None:
    f = _email_finding("info@co.example", "careers@co.example")
    out, why = _verify_email(f, _email_run(["info@co.example", "careers@co.example"]))
    assert why == "" and out.emails == ["careers@co.example"]


def test_other_types_are_untouched_by_the_email_gate() -> None:
    f = Findings(opportunity_type=OpportunityType.CAREERS_PAGE,
                 links=["https://co.example/careers"], emails=["sales@co.example"],
                 evidence="careers page", confidence=0.8)
    out, why = _verify_email(f, _email_run())
    assert out.opportunity_type is OpportunityType.CAREERS_PAGE
    assert out.emails == [] and why
