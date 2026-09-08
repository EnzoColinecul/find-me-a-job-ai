"""The trace panel's promise is 'nothing hidden' — these tests defend that."""
from fmaj_agent.trace import (
    TOOL_LABELS,
    Tag,
    TraceStep,
    summarise_tool_result,
    tool_label,
)


class _Result:
    """Stands in for a ToolResult: anything with model_dump()."""

    def __init__(self, **data):
        self._data = data

    def model_dump(self):
        return self._data


def test_every_label_names_a_tool_we_actually_run() -> None:
    """A label must never describe a call the agent doesn't make.

    The mockup shows a `places.details` row for a skipped company; we don't call
    Place Details during triage, so that label must not appear here.
    """
    from fmaj_agent.models import Company
    from fmaj_agent.orchestrator import _dispatch_for

    dispatch = _dispatch_for(
        Company(place_id="p", name="X", address="", roles=["chef"], country_code="au")
    )
    # `role_match` is not a model-callable tool but it IS a real call the agent
    # makes — an LLM judging vacancy titles against the role — and it gets its
    # own row when it rejects a claim, so it belongs here.
    known = set(dispatch) | {"discovery", "triage", "report_findings", "role_match"}
    assert set(TOOL_LABELS) == known
    assert "places.details" not in TOOL_LABELS.values()


def test_unmapped_tool_falls_back_to_its_real_name() -> None:
    assert tool_label("some_new_tool") == "some_new_tool"


def test_failed_tool_reads_as_skipping_not_found() -> None:
    tag, meta = summarise_tool_result(
        "fetch_url", {"url": "https://x.com"}, _Result(ok=False, reason="robots.txt")
    )
    assert tag is Tag.SKIPPING
    assert "robots" in meta


def test_empty_results_never_report_found() -> None:
    """Over-reporting success is the worst possible bug in a transparency panel."""
    for name, payload in [
        ("search_jobs_adzuna", {"jobs": []}),
        ("extract_emails", {"emails": []}),
        ("find_careers_link", {"url": ""}),
        # An employer page we couldn't verify must never read as a find.
        ("find_seek_company_page", {"job_count": 0}),
        # Vacancies exist but the role gate hasn't cleared any -> not a find.
        ("find_seek_company_page", {"job_count": 3}),
    ]:
        tag, _ = summarise_tool_result(name, {}, _Result(ok=True, **payload))
        assert tag is Tag.CHECKING, name


def test_real_results_report_found_with_a_count() -> None:
    tag, meta = summarise_tool_result(
        "search_jobs_adzuna", {}, _Result(ok=True, jobs=[1, 2])
    )
    assert tag is Tag.FOUND and meta == "2 matches"

    tag, meta = summarise_tool_result(
        "extract_emails", {},
        _Result(ok=True, emails=["careers@b.c"], recruitment=["careers@b.c"]),
    )
    assert tag is Tag.FOUND and meta == "1 recruitment email"


def test_a_bare_address_is_not_a_find() -> None:
    """"1 email" read as success for a `sales@` scraped off a dead site. An
    address only counts when a resume could plausibly reach a reader."""
    tag, meta = summarise_tool_result(
        "extract_emails", {}, _Result(ok=True, emails=["info@b.c"], recruitment=[]),
    )
    assert tag is Tag.CHECKING and "no hiring signal" in meta

    # …unless the page it came from invited applications.
    tag, meta = summarise_tool_result(
        "extract_emails", {},
        _Result(ok=True, emails=["info@b.c"], recruitment=[], hiring_signal=True),
    )
    assert tag is Tag.FOUND and "invites applications" in meta


def test_fetch_url_meta_is_a_bare_host() -> None:
    _, meta = summarise_tool_result(
        "fetch_url", {"url": "https://www.marloweskitchen.com.au/careers?x=1"}, _Result(ok=True)
    )
    assert meta == "www.marloweskitchen.com.au"


def test_missing_result_does_not_crash() -> None:
    tag, meta = summarise_tool_result("anything", {}, None)
    assert tag is Tag.CHECKING and meta == ""


def test_step_item_uses_the_friendly_label() -> None:
    item = TraceStep(tag=Tag.CHECKING, tool="fetch_url", text="Cafe X").to_item()
    assert item["tool"] == "fetch_page"
    assert item["tag"] == "checking"
    assert item["at"]


def test_seek_meta_names_the_matches_not_the_vacancy_count() -> None:
    """"3 Seek vacancies" for three off-role jobs is exactly the over-reporting
    this panel exists to avoid."""
    tag, meta = summarise_tool_result(
        "find_seek_company_page", {},
        _Result(ok=True, job_count=3, matching_count=1),
    )
    assert tag is Tag.FOUND and meta == "1 of 3 match the role"
