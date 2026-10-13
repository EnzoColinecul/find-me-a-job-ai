import json
from types import SimpleNamespace

import pytest
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from app import reconciler


def _event():
    serializer = TypeSerializer()
    meta = {
        "PK": "SEARCH#search123",
        "SK": "META",
        "search_id": "search123",
        "status": "pending",
        "lat": "-33.87",
        "lng": "151.21",
        "radius_km": "5.0",
        "roles": [{"label": "chef", "curated_key": None}],
        "user_sub": "u1",
        "created_at": "2026-09-29T00:00:00+00:00",
        "execution_start_state": "pending",
    }
    return {"Records": [{
        "eventName": "INSERT",
        "dynamodb": {"NewImage": {key: serializer.serialize(value) for key, value in meta.items()}},
    }]}


def test_stream_dispatch_starts_search_and_records_execution(monkeypatch):
    meta = {"status": "pending", "execution_start_state": "pending"}

    class Table:
        def get_item(self, **kwargs):
            assert kwargs["ConsistentRead"] is True
            return {"Item": meta}

        def update_item(self, **kwargs):
            assert "execution_start_state = :start_pending" in kwargs["ConditionExpression"]
            meta["execution_arn"] = kwargs["ExpressionAttributeValues"][":arn"]
            meta["execution_start_state"] = "started"

    class StateMachine:
        def __init__(self):
            self.calls = []

        def start_execution(self, **kwargs):
            self.calls.append(kwargs)
            return {"executionArn": "arn:aws:states:region:account:execution:machine:search-search123"}

    table = Table()
    sfn = StateMachine()
    monkeypatch.setattr(reconciler, "_get_table", lambda: table)
    monkeypatch.setattr(reconciler, "_get_sfn", lambda: sfn)
    monkeypatch.setattr(reconciler.os, "environ", {
        "FMAJ_STATE_MACHINE_ARN": "arn:aws:states:region:account:stateMachine:machine"
    })

    assert reconciler.handler(_event()) == {"started": 1}
    call = sfn.calls[0]
    assert call["name"] == "search-search123"
    assert json.loads(call["input"])["roles"][0]["label"] == "chef"
    assert meta["execution_start_state"] == "started"
    assert reconciler.handler(_event()) == {"started": 0}
    assert len(sfn.calls) == 1


def test_non_meta_stream_inserts_are_ignored(monkeypatch):
    monkeypatch.setattr(reconciler, "_get_table", lambda: pytest.fail("unexpected table read"))
    monkeypatch.setattr(reconciler, "_get_sfn", lambda: pytest.fail("unexpected workflow start"))
    event = _event()
    event["Records"][0]["dynamodb"]["NewImage"]["SK"] = {"S": "RESULT#place"}
    assert reconciler.handler(event) == {"started": 0}


def test_start_update_failure_can_be_retried_idempotently(monkeypatch):
    meta = {"status": "pending", "execution_start_state": "pending"}

    class Table:
        attempts = 0

        def get_item(self, **_kwargs):
            return {"Item": meta}

        def update_item(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise ClientError({"Error": {"Code": "InternalServerError"}}, "UpdateItem")
            meta["execution_arn"] = kwargs["ExpressionAttributeValues"][":arn"]
            meta["execution_start_state"] = "started"

    class StateMachine:
        def __init__(self):
            self.calls = []

        def start_execution(self, **kwargs):
            self.calls.append(kwargs)
            return {"executionArn": "arn:execution"}

    table = Table()
    sfn = StateMachine()
    monkeypatch.setattr(reconciler, "_get_table", lambda: table)
    monkeypatch.setattr(reconciler, "_get_sfn", lambda: sfn)
    monkeypatch.setattr(reconciler.os, "environ", {
        "FMAJ_STATE_MACHINE_ARN": "arn:state-machine"
    })

    with pytest.raises(ClientError):
        reconciler.handler(_event())
    assert reconciler.handler(_event()) == {"started": 1}
    assert len(sfn.calls) == 2
    assert sfn.calls[0]["name"] == sfn.calls[1]["name"] == "search-search123"


def test_permanent_start_failure_compensates_quota_and_lease_atomically(monkeypatch):
    actions = []

    class Client:
        def transact_write_items(self, **kwargs):
            actions.extend(kwargs["TransactItems"])

    class Table:
        meta = SimpleNamespace(client=Client())

        def get_item(self, **_kwargs):
            return {"Item": {"status": "pending", "execution_start_state": "pending"}}

    class BrokenStateMachine:
        def start_execution(self, **_kwargs):
            raise ClientError({"Error": {"Code": "AccessDeniedException"}}, "StartExecution")

    monkeypatch.setattr(reconciler, "_get_table", lambda: Table())
    monkeypatch.setattr(reconciler, "_get_sfn", lambda: BrokenStateMachine())
    monkeypatch.setattr(reconciler.os, "environ", {
        "FMAJ_STATE_MACHINE_ARN": "arn:state-machine",
        "FMAJ_TABLE_NAME": "table",
        "FMAJ_GLOBAL_MONTHLY_SEARCHES": "30",
    })

    assert reconciler.handler(_event()) == {"started": 0}
    assert len(actions) == 3
    expressions = [action["Update"]["UpdateExpression"] for action in actions]
    assert any("execution_start_state = :start_failed" in exp for exp in expressions)
    assert any("free_search_used = :unused" in exp for exp in expressions)
    assert any("ADD #c :minus" in exp for exp in expressions)
