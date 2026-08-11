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
    from fmaj_agent.orchestrator import _DISPATCH

    known = set(_DISPATCH) | {"discovery", "triage", "report_findings"}
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
    ]:
        tag, _ = summarise_tool_result(name, {}, _Result(ok=True, **payload))
        assert tag is Tag.CHECKING, name


def test_real_results_report_found_with_a_count() -> None:
    tag, meta = summarise_tool_result(
        "search_jobs_adzuna", {}, _Result(ok=True, jobs=[1, 2])
    )
    assert tag is Tag.FOUND and meta == "2 matches"

    tag, meta = summarise_tool_result("extract_emails", {}, _Result(ok=True, emails=["a@b.c"]))
    assert tag is Tag.FOUND and meta == "1 email"


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
