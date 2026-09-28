"""Workflow failures persist a safe code and terminal status truthfully."""
import json

from fmaj_agent import handlers


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
