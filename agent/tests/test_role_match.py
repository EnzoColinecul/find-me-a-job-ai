"""Role matching — the gate that stopped "is hiring" being read as "is hiring me".

The reported bug: a Melbourne "software developer" search returned Virtual IT
Group with a Seek link whose three vacancies were all other jobs. Every test
here is a stand-in for that.
"""
import pytest

from fmaj_agent import config, role_match
from fmaj_agent.models import ToolResult
from fmaj_agent.providers import Turn


class StubJudge:
    """A provider that answers the title-matching prompt from a lookup table."""

    def __init__(self, scores: dict[str, float] | None = None, text: str | None = None):
        self.scores = scores or {}
        self.text = text
        self.calls = 0

    def complete(self, _system, messages, **_kw) -> Turn:
        self.calls += 1
        if self.text is not None:
            return Turn(text=self.text)
        asked = [
            line[2:].strip()
            for line in messages[0]["text"].splitlines()
            if line.startswith("- ")
        ]
        verdicts = [
            {"title": t, "role": "x", "score": self.scores.get(t, 0.0), "why": "test"}
            for t in asked
        ]
        import json

        return Turn(text=json.dumps({"verdicts": verdicts}))


@pytest.fixture(autouse=True)
def _clear_cache():
    role_match._cache.clear()
    yield
    role_match._cache.clear()


def _judge(monkeypatch, **kw) -> StubJudge:
    stub = StubJudge(**kw)
    monkeypatch.setattr(role_match, "get_provider", lambda: stub)
    return stub


# ── the reported bug ───────────────────────────────────────────────────────

VIRTUAL_IT_GROUP = [
    "Service Desk Analyst",
    "Business Development Manager",
    "Account Manager",
]


def test_the_virtual_it_group_case(monkeypatch) -> None:
    """Three live vacancies, none of them a developer job -> no match."""
    _judge(monkeypatch, scores=dict.fromkeys(VIRTUAL_IT_GROUP, 0.1))
    report = role_match.match_titles(VIRTUAL_IT_GROUP, ["software developer"])
    assert not report.matched
    assert report.judged
    reason = report.refusal(["software developer"])
    assert "Business Development Manager" in reason
    assert "do not report this as a job listing" in reason.lower()


def test_the_seek_gate_suppresses_the_link(monkeypatch) -> None:
    """The whole point: an employer page with only off-role jobs returns no URL."""
    _judge(monkeypatch, scores=dict.fromkeys(VIRTUAL_IT_GROUP, 0.1))
    result = ToolResult(ok=True, data={
        "url": "https://au.seek.com/Virtual-IT-Group-jobs/at-this-company",
        "job_count": 3,
        "job_titles": VIRTUAL_IT_GROUP,
    })
    gated, report = role_match.gate_seek(result, ["software developer"])
    assert not gated.ok
    assert "seek.com" not in gated.reason  # no link leaks through the refusal
    assert report is not None and not report.matched


def test_the_seek_gate_keeps_a_real_match(monkeypatch) -> None:
    _judge(monkeypatch, scores={"Full Stack Engineer": 0.93, "Account Manager": 0.05})
    result = ToolResult(ok=True, data={
        "url": "https://au.seek.com/Acme-jobs/at-this-company",
        "job_count": 2,
        "job_titles": ["Full Stack Engineer", "Account Manager"],
    })
    gated, report = role_match.gate_seek(result, ["software developer"])
    assert gated.ok
    assert gated.data["matching_titles"] == ["Full Stack Engineer"]
    assert gated.data["matching_count"] == 1
    assert gated.data["job_count"] == 2  # the honest total is preserved


# ── judging ────────────────────────────────────────────────────────────────

def test_a_verbatim_role_needs_no_model_call(monkeypatch) -> None:
    """The cheap path: the role is written in the title, so don't pay to ask."""
    stub = _judge(monkeypatch, scores={})
    report = role_match.match_titles(["Software Developer (Graduate)"],
                                     ["software developer"])
    assert report.titles == ["Software Developer (Graduate)"]
    assert stub.calls == 0


def test_a_shared_word_is_not_a_match(monkeypatch) -> None:
    """"Business Development Manager" contains "development" — and is not the job."""
    assert role_match._obvious("Business Development Manager",
                               ["software developer"]) is None
    assert role_match._obvious("Kitchen Designer", ["kitchen hand"]) is None


def test_threshold_is_the_bar(monkeypatch) -> None:
    _judge(monkeypatch, scores={"Junior Coder": 0.79, "Backend Engineer": 0.81})
    report = role_match.match_titles(["Junior Coder", "Backend Engineer"],
                                     ["software developer"])
    assert report.titles == ["Backend Engineer"]


def test_threshold_is_configurable(monkeypatch) -> None:
    monkeypatch.setattr(config, "ROLE_MATCH_THRESHOLD", 0.5)
    _judge(monkeypatch, scores={"Junior Coder": 0.6})
    assert role_match.match_titles(["Junior Coder"], ["software developer"]).matched


def test_a_broken_threshold_env_does_not_disable_the_gate(monkeypatch) -> None:
    """0 means 'unlimited' for budgets; here it would mean 'match everything'."""
    for bad in ("0", "lots", "-1", "5"):
        monkeypatch.setenv("FMAJ_ROLE_MATCH_BAD", bad)
        assert config._ratio("FMAJ_ROLE_MATCH_BAD", 0.8) == 0.8


# ── failing closed ─────────────────────────────────────────────────────────

def test_an_unreachable_judge_is_not_a_match(monkeypatch) -> None:
    """Surfacing an unverified listing is the bug; showing one fewer link isn't."""
    class Boom:
        def complete(self, *a, **kw):
            raise RuntimeError("vertex is down")

    monkeypatch.setattr(role_match, "get_provider", lambda: Boom())
    report = role_match.match_titles(["Service Desk Analyst"], ["software developer"])
    assert not report.matched and not report.judged
    # "couldn't check these" reads differently from "couldn't read any" — the
    # trace has to be able to tell a dead judge from an unreadable page.
    assert "could not check" in report.refusal(["software developer"])


def test_unparseable_output_is_not_a_match(monkeypatch) -> None:
    _judge(monkeypatch, text="I'm afraid I can't do that")
    assert not role_match.match_titles(["Service Desk Analyst"], ["chef"]).matched


def test_no_titles_is_not_a_match(monkeypatch) -> None:
    """An employer page whose titles we couldn't read must not become a link."""
    result = ToolResult(ok=True, data={"url": "https://au.seek.com/X-jobs/at-this-company",
                                       "job_count": 3, "job_titles": []})
    gated, _ = role_match.gate_seek(result, ["chef"])
    assert not gated.ok and "could not read" in gated.reason


def test_a_title_we_never_sent_is_ignored(monkeypatch) -> None:
    """The judge inventing a title must not create a match out of nothing."""
    import json

    _judge(monkeypatch, text=json.dumps(
        {"verdicts": [{"title": "Software Developer", "score": 1.0}]}))
    report = role_match.match_titles(["Service Desk Analyst"], ["software developer"])
    assert not report.matched


# ── adzuna + provenance ────────────────────────────────────────────────────

def test_adzuna_hits_are_filtered_not_trusted(monkeypatch) -> None:
    """Adzuna matches the company name loosely and returns whatever it's hiring."""
    _judge(monkeypatch, scores={"Warehouse Picker": 0.05, "Sous Chef": 0.9})
    result = ToolResult(ok=True, data={"jobs": [
        {"title": "Warehouse Picker", "url": "https://adzuna/1"},
        {"title": "Sous Chef", "url": "https://adzuna/2"},
    ]})
    gated, _ = role_match.gate_adzuna(result, ["chef"])
    assert gated.ok
    assert [j["title"] for j in gated.data["jobs"]] == ["Sous Chef"]
    assert gated.data["dropped_off_role"] == 1


def test_adzuna_with_nothing_matching_refuses(monkeypatch) -> None:
    _judge(monkeypatch, scores={"Warehouse Picker": 0.05})
    result = ToolResult(ok=True, data={"jobs": [{"title": "Warehouse Picker"}]})
    gated, _ = role_match.gate_adzuna(result, ["chef"])
    assert not gated.ok and "Warehouse Picker" in gated.reason


def test_a_failed_tool_passes_through_ungated() -> None:
    """Gating must not turn a tool's own reason into a matching one."""
    result = ToolResult(ok=False, reason="http 404")
    assert role_match.gate_seek(result, ["chef"])[0].reason == "http 404"
    assert role_match.gate_adzuna(result, ["chef"])[0].reason == "http 404"


def test_observed_titles_names_what_the_model_saw() -> None:
    seek = ToolResult(ok=True, data={"job_titles": ["Sous Chef"]})
    adzuna = ToolResult(ok=True, data={"jobs": [{"title": "Chef de Partie"}]})
    search = ToolResult(ok=True, data={"results": [{"title": "Chef jobs | SEEK"}]})
    assert role_match.observed_titles("find_seek_company_page", seek) == ["Sous Chef"]
    assert role_match.observed_titles("search_jobs_adzuna", adzuna) == ["Chef de Partie"]
    assert role_match.observed_titles("web_search", search) == ["Chef jobs | SEEK"]
    assert role_match.observed_titles("fetch_url", seek) == []
    assert role_match.observed_titles("find_seek_company_page", None) == []


def test_titles_are_judged_once_per_run(monkeypatch) -> None:
    """The report gate re-checks the same title the tool gate already cleared."""
    stub = _judge(monkeypatch, scores={"Backend Engineer": 0.9})
    for _ in range(3):
        role_match.match_titles(["Backend Engineer"], ["software developer"])
    assert stub.calls == 1
