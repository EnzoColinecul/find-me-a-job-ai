"""Langfuse observability: trace shape, error capture, fail-safe, redaction.

Spans are captured with OpenTelemetry's in-memory exporter, so these tests read
exactly what would have been sent to Langfuse Cloud — without sending it.
"""
import itertools
import json
import time

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from fmaj_agent import handlers, observability, orchestrator, role_match
from fmaj_agent.models import Company, OpportunityType, ToolResult
from fmaj_agent.providers import Provider, ToolUse, Turn

SEARCH_ID = "abc123def456"
_keys = itertools.count()

# Sensitive values planted in the run. None of them may appear in any span.
COMPANY = "Ramen Secret Kitchen"
ADDRESS = "12 Private Lane, Surry Hills NSW 2010"
WEBSITE = "https://ramen-secret-kitchen.example.com/"
EMAIL = "jobs@ramen-secret-kitchen.example.com"
PAGE_TEXT = "Please send us your resume. Our head chef Hiroshi says hi."
API_KEY = "sk-lf-THIS-MUST-NEVER-LEAVE-1234567890"


@pytest.fixture
def spans():
    """Install a real Langfuse client that exports to memory. Yields a reader."""
    from langfuse import Langfuse

    exporter = InMemorySpanExporter()
    n = next(_keys)  # Langfuse caches clients per public key
    lf = Langfuse(
        public_key=f"pk-lf-test-{n}", secret_key=f"sk-lf-test-{n}",
        base_url="http://127.0.0.1:9", environment="test",
        mask=observability._mask, span_exporter=exporter,
        tracer_provider=TracerProvider(),
    )
    observability.set_client(lf)

    def read():
        lf.flush()
        return list(exporter.get_finished_spans())

    yield read
    observability.disable()


def _attrs(span) -> dict:
    return dict(span.attributes or {})


def _by_name(spans, name):
    return [s for s in spans if s.name == name]


def _all_text(spans) -> str:
    return json.dumps([{**_attrs(s), "__name": s.name} for s in spans], default=str)


class ScriptedProvider(Provider):
    """A provider that replays turns but goes through the REAL `complete`, so
    generations are recorded exactly as for Gemini/Bedrock."""

    name = "scripted"

    def __init__(self, turns):
        self.turns = list(turns)

    def _complete(self, system, messages, **kw):
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


def _tool(name, **args):
    return Turn(tool_uses=[ToolUse(id="t", name=name, input=args)],
                input_tokens=100, output_tokens=20)


def _company(**kw) -> Company:
    return Company(place_id="ChIJplace", name=COMPANY, address=ADDRESS,
                   website=WEBSITE, roles=["chef"], country_code="au", **kw)


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr(orchestrator, "fetch_url", lambda url: ToolResult(
        ok=True, data={"url": url, "text": PAGE_TEXT, "hiring_signal": True}))
    monkeypatch.setattr(orchestrator, "extract_emails", lambda url: ToolResult(
        ok=True, data={"url": url, "emails": [EMAIL], "hiring_signal": True}))
    monkeypatch.setattr(orchestrator, "web_search", lambda q: ToolResult(
        ok=False, reason=f"SerpAPI failed for {q} with key {API_KEY}"))
    role_match._cache.clear()


def _use(monkeypatch, provider):
    # One instance for the whole run: triage and the tool loop share it.
    monkeypatch.setattr(orchestrator, "get_provider", lambda: provider)


def _happy_provider():
    return ScriptedProvider([
        Turn(text='{"plausible": true}', input_tokens=40, output_tokens=5),
        _tool("fetch_url", url=WEBSITE),
        _tool("extract_emails", url=WEBSITE + "contact"),
        _tool("report_findings", opportunity_type="contact_email", emails=[EMAIL],
              links=[WEBSITE + "contact"], evidence=f"{PAGE_TEXT} {EMAIL}",
              confidence=0.8),
    ])


# ── trace creation ─────────────────────────────────────────────────────────

def test_a_search_produces_one_trace_with_nested_observations(spans, tools, monkeypatch):
    provider = _happy_provider()
    monkeypatch.setattr(orchestrator, "get_provider", lambda: provider)
    run = orchestrator.investigate(_company(), search_id=SEARCH_ID)
    assert run.findings.opportunity_type is OpportunityType.CONTACT_EMAIL

    got = spans()
    trace_id = observability.trace_id_for(SEARCH_ID)
    assert {format(s.context.trace_id, "032x") for s in got} == {trace_id}

    (company,) = _by_name(got, "company")
    a = _attrs(company)
    assert a["langfuse.observation.type"] == "agent"
    assert a["langfuse.trace.name"] == "search"
    assert a["langfuse.trace.metadata.search_id"] == SEARCH_ID
    assert a["langfuse.trace.metadata.country_code"] == "au"
    assert a["langfuse.trace.metadata.role"] == "chef"
    assert a["langfuse.observation.metadata.place_id"] == "ChIJplace"
    assert "provider:gemini" in a["langfuse.trace.tags"] or any(
        t.startswith("provider:") for t in a["langfuse.trace.tags"])
    out = json.loads(a["langfuse.observation.output"])
    assert out["opportunity_type"] == "contact_email"

    # everything else hangs under the company observation
    children = [s for s in got if s is not company]
    assert children and all(s.parent and s.parent.span_id == company.context.span_id
                            for s in children)

    (triage,) = _by_name(got, "triage")
    ta = _attrs(triage)
    assert ta["langfuse.observation.type"] == "generation"
    assert json.loads(ta["langfuse.observation.usage_details"]) == {
        "input": 40, "output": 5, "total": 45}
    assert ta["langfuse.observation.metadata.provider"] == "scripted"
    assert len(_by_name(got, "agent.turn")) == 3
    assert [s.name for s in got if s.name.startswith("tool.")] == [
        "tool.fetch_url", "tool.extract_emails"]


def test_tool_errors_and_budget_events_are_visible(spans, tools, monkeypatch):
    monkeypatch.setattr(orchestrator.config, "MAX_WEB_SEARCHES", 1)
    monkeypatch.setattr(orchestrator.config, "MAX_TOOL_CALLS", 3)
    _use(monkeypatch, ScriptedProvider([
        Turn(text='{"plausible": true}'),
        _tool("web_search", query=f"{COMPANY} careers"),
        _tool("web_search", query=f"{COMPANY} jobs"),       # over the per-company cap
        _tool("fetch_url", url=WEBSITE),                    # third call: budget spent
        _tool("report_findings", opportunity_type="none", evidence="", confidence=0),
    ]))
    run = orchestrator.investigate(_company(), search_id=SEARCH_ID)
    assert run.forced_report

    got = spans()
    (ws,) = _by_name(got, "tool.web_search")
    assert _attrs(ws)["langfuse.observation.level"] == "WARNING"
    assert json.loads(_attrs(ws)["langfuse.observation.output"])["ok"] is False
    assert _by_name(got, "budget.denied")
    (breach,) = _by_name(got, "budget.breach")
    assert _attrs(breach)["langfuse.observation.level"] == "WARNING"
    assert _by_name(got, "forced_report")
    (company,) = _by_name(got, "company")
    assert json.loads(_attrs(company)["langfuse.observation.output"])["forced_report"] is True


# ── error capture ──────────────────────────────────────────────────────────

def test_a_model_failure_is_recorded_and_the_run_still_returns(spans, tools, monkeypatch):
    _use(monkeypatch, ScriptedProvider([
        RuntimeError("vertex exploded"),
    ]))
    run = orchestrator.investigate(_company(), search_id=SEARCH_ID)
    assert run.error and run.findings.opportunity_type is OpportunityType.NONE

    got = spans()
    (triage,) = _by_name(got, "triage")
    assert _attrs(triage)["langfuse.observation.level"] == "ERROR"
    assert "vertex exploded" in _attrs(triage)["langfuse.observation.status_message"]
    (company,) = _by_name(got, "company")
    assert _attrs(company)["langfuse.observation.level"] == "ERROR"
    assert json.loads(_attrs(company)["langfuse.observation.output"])["error"]


def test_the_callers_exception_propagates_unchanged(spans):
    with pytest.raises(KeyError), observability.observe("x", search_id=SEARCH_ID):
        raise KeyError("boom")
    (x,) = _by_name(spans(), "x")
    assert _attrs(x)["langfuse.observation.level"] == "ERROR"


def test_pipeline_steps_join_the_same_trace(spans, monkeypatch):
    class Table:
        def update_item(self, **kw):
            pass

    monkeypatch.setattr(handlers, "_get_table", lambda: Table())
    handlers.aggregate_handler({"search_id": SEARCH_ID, "results": [
        {"opportunity_type": "careers_page"}, {"opportunity_type": "none"}]})
    handlers.fail_handler({"search_id": SEARCH_ID, "error": {
        "Error": "States.TaskFailed", "Cause": f"Traceback… {EMAIL} {API_KEY}"}})

    got = spans()
    assert {format(s.context.trace_id, "032x") for s in got} == {
        observability.trace_id_for(SEARCH_ID)}
    (agg,) = _by_name(got, "aggregate")
    assert json.loads(_attrs(agg)["langfuse.observation.output"])["counts"] == {
        "careers_page": 1, "none": 1}
    (failed,) = _by_name(got, "search.failed")
    assert _attrs(failed)["langfuse.observation.level"] == "ERROR"
    assert EMAIL not in _all_text(got) and API_KEY not in _all_text(got)


def test_trace_id_matches_langfuse_seeded_ids():
    from langfuse import Langfuse

    assert observability.trace_id_for(SEARCH_ID) == Langfuse.create_trace_id(
        seed=f"fmaj-search:{SEARCH_ID}")


# ── disabled / missing keys / unavailable ──────────────────────────────────

@pytest.fixture
def no_config(monkeypatch, tmp_path):
    for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL",
              "LANGFUSE_HOST", "FMAJ_LANGFUSE_SECRET", "FMAJ_LANGFUSE_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(observability, "_repo_env_file", lambda: tmp_path / ".env")
    observability.set_client(None)


def test_missing_keys_mean_tracing_off_and_searches_still_work(no_config, tools, monkeypatch):
    assert observability.client() is None
    provider = _happy_provider()
    monkeypatch.setattr(orchestrator, "get_provider", lambda: provider)
    run = orchestrator.investigate(_company(), search_id=SEARCH_ID)
    assert run.findings.opportunity_type is OpportunityType.CONTACT_EMAIL
    observability.flush()  # a no-op, not an error


def test_the_kill_switch_wins_over_keys(no_config, monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-x")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-x")
    monkeypatch.setenv("FMAJ_LANGFUSE_ENABLED", "0")
    assert observability.client() is None


def test_an_unreadable_secret_disables_tracing_instead_of_raising(no_config, monkeypatch):
    from fmaj_agent import secrets

    def boom(name):
        raise RuntimeError("AccessDenied")

    monkeypatch.setenv("FMAJ_LANGFUSE_SECRET", "fmaj/test/langfuse")
    monkeypatch.setattr(secrets, "_secret_string", boom)
    assert observability.client() is None


def test_keys_resolve_env_then_dotenv_then_secrets_manager(no_config, monkeypatch, tmp_path):
    from fmaj_agent import secrets

    # 1. Secrets Manager (deployed stages)
    monkeypatch.setenv("FMAJ_LANGFUSE_SECRET", "fmaj/test/langfuse")
    monkeypatch.setattr(secrets, "_secret_string", lambda name: json.dumps(
        {"public_key": "pk-sm", "secret_key": "sk-sm"}))
    assert observability._credentials() == ("pk-sm", "sk-sm", observability.DEFAULT_BASE_URL)

    # 2. repo-root .env beats it — and ONLY the LANGFUSE_* names are read from it
    (tmp_path / ".env").write_text(
        "AWS_SECRET_ACCESS_KEY=never-exported\nLANGFUSE_PUBLIC_KEY=pk-file\n"
        'LANGFUSE_SECRET_KEY="sk-file"\nLANGFUSE_BASE_URL=https://us.cloud.langfuse.com\n')
    assert observability._credentials() == ("pk-file", "sk-file", "https://us.cloud.langfuse.com")
    import os
    assert "AWS_SECRET_ACCESS_KEY" not in os.environ or os.environ[
        "AWS_SECRET_ACCESS_KEY"] != "never-exported"

    # 3. the process environment beats both
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-env")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-env")
    assert observability._credentials()[:2] == ("pk-env", "sk-env")

    # never from a file inside Lambda
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY")
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "fn")
    assert observability._credentials()[0] == "pk-sm"


def test_a_langfuse_client_that_throws_never_reaches_the_search(tools, monkeypatch):
    class Broken:
        def start_as_current_observation(self, **kw):
            raise RuntimeError("otel is sad")

        def create_event(self, **kw):
            raise RuntimeError("otel is sad")

        def flush(self):
            raise RuntimeError("otel is sad")

    observability.set_client(Broken())
    provider = _happy_provider()
    monkeypatch.setattr(orchestrator, "get_provider", lambda: provider)
    run = orchestrator.investigate(_company(), search_id=SEARCH_ID)
    assert run.findings.opportunity_type is OpportunityType.CONTACT_EMAIL
    assert run.error is None
    observability.flush()


def test_an_unreachable_langfuse_costs_at_most_the_flush_timeout(tools, monkeypatch):
    from langfuse import Langfuse

    n = next(_keys)
    observability.set_client(Langfuse(
        public_key=f"pk-lf-down-{n}", secret_key="sk-lf-down",
        base_url="http://127.0.0.1:9", timeout=1, tracer_provider=TracerProvider()))
    provider = _happy_provider()
    monkeypatch.setattr(orchestrator, "get_provider", lambda: provider)
    run = orchestrator.investigate(_company(), search_id=SEARCH_ID)
    assert run.findings.opportunity_type is OpportunityType.CONTACT_EMAIL
    start = time.monotonic()
    observability.flush(timeout=0.5)
    assert time.monotonic() - start < 1.5


# ── redaction ──────────────────────────────────────────────────────────────

def test_nothing_sensitive_reaches_langfuse(spans, tools, monkeypatch):
    _use(monkeypatch, ScriptedProvider([
        Turn(text='{"plausible": true}'),
        _tool("fetch_url", url=WEBSITE),
        _tool("web_search", query=f"{COMPANY} careers"),
        _tool("extract_emails", url=WEBSITE + "contact"),
        _tool("report_findings", opportunity_type="contact_email", emails=[EMAIL],
              links=[WEBSITE + "contact"], evidence=f"{PAGE_TEXT} {EMAIL}",
              confidence=0.8),
    ]))
    orchestrator.investigate(_company(), search_id=SEARCH_ID)
    blob = _all_text(spans())
    for secret in (COMPANY, ADDRESS, WEBSITE, "ramen-secret-kitchen", EMAIL,
                   PAGE_TEXT, "Hiroshi", API_KEY):
        assert secret not in blob, secret


@pytest.mark.parametrize("raw, gone, kept", [
    ("mail jobs@acme.com now", "jobs@acme.com", "[email]"),
    ("see https://acme.com/careers?token=abc", "token=abc", "<url:acme.com>"),
    ("Authorization: Bearer abc.def.ghi", "abc.def.ghi", "[redacted-token]"),
    ("jwt eyJhbGciOi.eyJzdWIiOiIx.c2lnbmF0dXJl", "eyJzdWIiOiIx", "[redacted-token]"),
    ("key sk-lf-1234567890abcdef", "sk-lf-1234567890abcdef", "[redacted-secret]"),
    ("serp " + "a1" * 32, "a1" * 32, "[redacted-secret]"),
    ("google AIzaSyA-1234567890abcdefgh", "AIzaSyA-1234567890", "[redacted-secret]"),
])
def test_redact_text(raw, gone, kept):
    out = observability.redact_text(raw)
    assert gone not in out and kept in out


def test_redact_structures():
    out = observability.redact({
        "secret_key": "x", "api_key": "x", "text": "page body", "messages": [1],
        "company": COMPANY, "address": ADDRESS, "emails": [EMAIL],
        "input_tokens": 12, "emails_count": 2, "nested": {"authorization": "x",
                                                          "note": "a" * 1000},
    })
    for k in ("secret_key", "api_key", "text", "messages", "company", "address", "emails"):
        assert out[k] == "[redacted]", k
    assert out["input_tokens"] == 12 and out["emails_count"] == 2
    assert out["nested"]["authorization"] == "[redacted]"
    assert len(out["nested"]["note"]) <= observability.MAX_STRING + 1


def test_tool_summaries_carry_shape_not_content():
    assert observability.tool_input_summary({"url": WEBSITE, "query": COMPANY}) == {
        "url": f"<str:{len(WEBSITE)}>", "query": f"<str:{len(COMPANY)}>"}
    s = observability.tool_output_summary(ToolResult(
        ok=True, data={"text": PAGE_TEXT, "emails": [EMAIL], "job_count": 3,
                       "hiring_signal": True}))
    assert s == {"ok": True, "data": {"text_chars": len(PAGE_TEXT), "emails_count": 1,
                                      "job_count": 3, "hiring_signal": True}}
