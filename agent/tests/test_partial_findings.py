"""Interrupted investigations retain only source-backed, already verified leads."""
import pytest

from fmaj_agent import config, orchestrator, role_match
from fmaj_agent.deadline import deadline_after
from fmaj_agent.models import Company, Findings, OpportunityType, ToolResult
from fmaj_agent.orchestrator import AgentRun, EvidenceRecord, _recover_observed_findings
from fmaj_agent.providers import ToolUse, Turn


def evidence(run, kind, value, url, tool, *, company_id=None, hiring=False):
    run.evidence_records.append(EvidenceRecord(
        company_id=company_id or run.company_id, claim_type=kind,
        claim_value=value, source_url=url, source_type=tool,
        observed_at=1, hiring_signal=hiring,
    ))


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setattr(role_match, "match_titles", lambda *args: pytest.fail("recovery called the model"))
    return AgentRun(findings=Findings(opportunity_type=OpportunityType.NONE), company_id="acme")


def test_recovery_keeps_previously_verified_vacancy_and_location_warning(run):
    url = "https://adzuna.example/123"
    run.verified_titles = {"chef"}
    run.observed_titles = {"chef": "Chef"}
    run.title_sources = {"chef": {url}}
    run.observed_urls = {url}
    run.location_uncertain_titles = {"chef"}
    evidence(run, "vacancy_title", "chef", url, "search_jobs_adzuna")
    with deadline_after(0):
        finding = _recover_observed_findings(run, "model timeout")
    assert finding.opportunity_type is OpportunityType.JOB_LISTING
    assert finding.matched_title == "Chef"
    assert finding.links == [url]
    assert "location has not been confirmed" in finding.evidence
    assert finding.confidence <= 0.5


def test_recovery_keeps_explicit_careers_link(run):
    url = "https://acme.example/careers"
    run.observed_urls = {url}
    evidence(run, "url", url, url, "find_careers_link")
    finding = _recover_observed_findings(run, "model timeout")
    assert finding.opportunity_type is OpportunityType.CAREERS_PAGE
    assert finding.links == [url]
    assert "Partial check" in finding.evidence


@pytest.mark.parametrize("source", ["fetch_url", "web_search", "find_seek_company_page"])
def test_recovery_does_not_promote_arbitrary_observed_urls(run, source):
    url = "https://acme.example"
    run.observed_urls = {url}
    evidence(run, "url", url, url, source)
    assert _recover_observed_findings(run, "timeout").opportunity_type is OpportunityType.NONE


@pytest.mark.parametrize("verified,owner", [(False, "acme"), (True, "other")])
def test_recovery_rejects_unjudged_or_wrong_company_vacancies(run, verified, owner):
    url = "https://board.example/123"
    run.verified_titles = {"chef"} if verified else set()
    run.observed_titles = {"chef": "Chef"}
    run.title_sources = {"chef": {url}}
    run.observed_urls = {url}
    evidence(run, "vacancy_title", "chef", url, "search_jobs_adzuna", company_id=owner)
    assert _recover_observed_findings(run, "timeout").opportunity_type is OpportunityType.NONE


@pytest.mark.parametrize("email,hiring,owner,accepted", [
    ("careers@acme.example", False, "acme", True),
    ("info@acme.example", True, "acme", True),
    ("info@acme.example", False, "acme", False),
    ("careers@acme.example", False, "other", False),
])
def test_recovery_uses_existing_email_provenance_gate(run, email, hiring, owner, accepted):
    url = "https://acme.example/contact"
    run.observed_emails = {email: email}
    run.observed_email_sources = {email: (url, hiring)}
    evidence(run, "email", email, url, "extract_emails", company_id=owner, hiring=hiring)
    finding = _recover_observed_findings(run, "timeout")
    assert bool(finding.emails) is accepted
    assert finding.opportunity_type is (OpportunityType.CONTACT_EMAIL if accepted else OpportunityType.NONE)


@pytest.mark.parametrize("forced", [False, True])
def test_late_model_error_retains_lead_and_error_status(monkeypatch, forced):
    class Provider:
        calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return Turn(text='{"plausible": true}')
            if self.calls == 2:
                return Turn(tool_uses=[ToolUse("1", "find_careers_link", {"url": "https://acme.example"})])
            raise TimeoutError("provider timeout")

    # Triage and tool loop share the same provider instance.
    provider = Provider()
    monkeypatch.setattr(orchestrator, "get_provider", lambda: provider)
    monkeypatch.setattr(orchestrator, "find_careers_link", lambda url: ToolResult(
        ok=True, data={"candidates": ["https://acme.example/careers"]}))
    monkeypatch.setattr(config, "MAX_TOOL_CALLS", 1 if forced else 8)
    result = orchestrator.investigate(Company(
        place_id="acme", name="Acme", address="Melbourne", country_code="au",
        website="https://acme.example", roles=["chef"],
    ))
    assert result.error.startswith("TimeoutError:")
    assert result.findings.opportunity_type is OpportunityType.CAREERS_PAGE
    assert result.findings.links == ["https://acme.example/careers"]
    assert result.forced_report is forced


def test_time_budget_recovery_does_not_request_final_model_report(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(orchestrator.time, "monotonic", lambda: clock[0])

    class Provider:
        calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return Turn(text='{"plausible": true}')
            assert self.calls == 2
            return Turn(tool_uses=[ToolUse("1", "find_careers_link", {"url": "https://acme.example"})])

    def careers(url):
        clock[0] = 58
        return ToolResult(ok=True, data={"candidates": ["https://acme.example/careers"]})

    provider = Provider()
    monkeypatch.setattr(orchestrator, "get_provider", lambda: provider)
    monkeypatch.setattr(orchestrator, "find_careers_link", careers)
    monkeypatch.setattr(config, "MAX_TOOL_CALLS", 1)
    result = orchestrator.investigate(Company(
        place_id="acme", name="Acme", address="Melbourne", country_code="au",
        website="https://acme.example", roles=["chef"],
    ))
    assert result.error.startswith("TimeoutError:")
    assert result.findings.opportunity_type is OpportunityType.CAREERS_PAGE
    assert provider.calls == 2


def test_cancellation_during_failed_request_does_not_recover_leads(monkeypatch):
    stopped = False

    class Provider:
        calls = 0

        def complete(self, *args, **kwargs):
            nonlocal stopped
            self.calls += 1
            if self.calls == 1:
                return Turn(text='{"plausible": true}')
            if self.calls == 2:
                return Turn(tool_uses=[ToolUse("1", "find_careers_link", {"url": "https://acme.example"})])
            stopped = True
            raise TimeoutError("provider timeout")

    provider = Provider()
    monkeypatch.setattr(orchestrator, "get_provider", lambda: provider)
    monkeypatch.setattr(orchestrator, "find_careers_link", lambda url: ToolResult(
        ok=True, data={"candidates": ["https://acme.example/careers"]}))
    result = orchestrator.investigate(Company(
        place_id="acme", name="Acme", address="Melbourne", country_code="au",
        website="https://acme.example", roles=["chef"],
    ), should_stop=lambda: stopped)
    assert result.cancelled
    assert result.findings.opportunity_type is OpportunityType.NONE
