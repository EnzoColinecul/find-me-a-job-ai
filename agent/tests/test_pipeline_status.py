"""Workflow failures persist a safe code and terminal status truthfully."""
import json
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from fmaj_agent import handlers
from fmaj_agent.models import Findings, OpportunityType


class CapturingTable:
    def __init__(self):
        self.update = None

    def update_item(self, **kwargs):
        self.update = kwargs


def test_step_function_timeout_event_finds_search_and_marks_retryable(monkeypatch):
    table = CapturingTable()
    monkeypatch.setattr(handlers, "_get_table", lambda: table)
    result = handlers.fail_handler({"detail": {
        "status": "TIMED_OUT",
        "input": json.dumps({"search_id": "timeout-search"}),
        "cause": "never persist request input or stack traces",
    }})

    assert result == {
        "search_id": "timeout-search", "status": "failed",
        "error_code": "workflow_timeout", "retryable": True,
    }
    assert table.update["ExpressionAttributeValues"][":ec"] == "workflow_timeout"
    assert table.update["ExpressionAttributeValues"][":r"] is True
    assert "ConditionExpression" in table.update
    assert "cause" not in table.update["ExpressionAttributeValues"]


def test_permission_failure_is_safe_and_not_retryable(monkeypatch):
    table = CapturingTable()
    monkeypatch.setattr(handlers, "_get_table", lambda: table)
    result = handlers.fail_handler({"search_id": "permission-search", "error": {
        "Error": "States.Permissions", "Cause": "sensitive details",
    }})

    assert result["error_code"] == "permission_denied"
    assert result["retryable"] is False
    assert "sensitive details" not in repr(table.update)


def test_conditional_write_checks_running_state_in_same_transaction(monkeypatch):
    class Client:
        transaction = None

        def transact_write_items(self, **kwargs):
            self.transaction = kwargs["TransactItems"]

    table = SimpleNamespace(name="searches", meta=SimpleNamespace(client=Client()))
    monkeypatch.setattr(handlers, "_get_table", lambda: table)
    handlers._write_while_running("s1", [{"Put": {
        "TableName": "searches", "Item": {"PK": {"S": "SEARCH#s1"}},
    }}])

    check, put = table.meta.client.transaction
    assert check["ConditionCheck"]["ConditionExpression"] == "#s = :running"
    assert check["ConditionCheck"]["ExpressionAttributeValues"][":running"] == {"S": "running"}
    assert put["Put"]["Item"]["PK"] == {"S": "SEARCH#s1"}


def test_conditional_write_retries_transaction_conflicts_with_same_token(monkeypatch):
    class Client:
        calls = 0
        tokens = []

        def transact_write_items(self, **kwargs):
            self.calls += 1
            self.tokens.append(kwargs["ClientRequestToken"])
            if self.calls == 1:
                raise ClientError({"Error": {"Code": "TransactionConflictException"}},
                                  "TransactWriteItems")

    client = Client()
    table = SimpleNamespace(name="searches", meta=SimpleNamespace(client=client))
    monkeypatch.setattr(handlers, "_get_table", lambda: table)
    monkeypatch.setattr(handlers.time, "sleep", lambda _delay: None)
    handlers._write_while_running("s1", [{"Put": {
        "TableName": "searches", "Item": {"PK": {"S": "SEARCH#s1"}},
    }}])

    assert client.calls == 2
    assert client.tokens[0] == client.tokens[1]


def test_result_transaction_cancellation_does_not_write_after_stop(monkeypatch):
    class Client:
        def transact_write_items(self, **_kwargs):
            raise ClientError({"Error": {"Code": "TransactionCanceledException"}},
                              "TransactWriteItems")

    table = SimpleNamespace(name="searches", meta=SimpleNamespace(client=Client()))
    monkeypatch.setattr(handlers, "_get_table", lambda: table)
    checks = iter([False, False, True])
    monkeypatch.setattr(handlers, "_search_stopped", lambda _sid: next(checks))
    monkeypatch.setattr(handlers, "_search_cancelled", lambda _sid: True)
    monkeypatch.setattr(handlers, "investigate", lambda *_args, **_kwargs: SimpleNamespace(
        cancelled=False,
        findings=Findings(opportunity_type=OpportunityType.NONE),
        stats=lambda: {},
        tool_calls=0,
        metered_calls={},
        input_tokens=0,
        output_tokens=0,
        error=None,
    ))

    result = handlers.investigate_handler({
        "search_id": "s1",
        "company": {"place_id": "p1", "name": "Cafe", "address": "Melbourne",
                    "roles": ["chef"], "country_code": "au"},
    })
    assert result["outcome"] == "cancelled"
