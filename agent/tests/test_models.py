from fmaj_agent.models import Findings, OpportunityType


def test_findings_schema_defaults() -> None:
    f = Findings(opportunity_type=OpportunityType.NONE)
    assert f.links == [] and f.emails == []
    assert 0.0 <= f.confidence <= 1.0


def test_opportunity_type_values() -> None:
    assert OpportunityType.JOB_LISTING.value == "job_listing"
    assert OpportunityType("careers_page") == OpportunityType.CAREERS_PAGE
