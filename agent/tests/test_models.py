from fmaj_agent.models import Company, Findings, OpportunityType
from fmaj_agent.orchestrator import investigate


def test_findings_schema_defaults() -> None:
    f = Findings(opportunity_type=OpportunityType.NONE)
    assert f.links == [] and f.emails == []
    assert 0.0 <= f.confidence <= 1.0


def test_investigate_never_raises() -> None:
    company = Company(place_id="x", name="Test Cafe", address="Sydney", roles=["barista"])
    findings = investigate(company)
    assert isinstance(findings, Findings)
