"""Exercise handler transactions through Boto3's actual resource serializer."""
import json
from types import SimpleNamespace

import boto3
import pytest
from botocore.awsrequest import AWSResponse

from fmaj_agent import handlers
from fmaj_agent.models import Company, Findings, OpportunityType
from fmaj_agent.trace import Tag, TraceStep


@pytest.fixture
def wire_requests(monkeypatch):
    resource = boto3.resource(
        "dynamodb", region_name="ap-southeast-2",
        aws_access_key_id="testing", aws_secret_access_key="testing",
    )
    requests = []

    def capture(model, params, **_kwargs):
        requests.append((model.name, json.loads(params["body"])))
        return AWSResponse("https://offline.invalid", 200, {}, None), {}

    resource.meta.client.meta.events.register("before-call.dynamodb", capture)
    monkeypatch.setattr(handlers, "_get_table", lambda: resource.Table("table"))
    return requests


def _transactions(requests):
    return [request["TransactItems"] for operation, request in requests
            if operation == "TransactWriteItems"]


def _assert_running_check(action):
    check = action["ConditionCheck"]
    assert check["Key"] == {"PK": {"S": "SEARCH#s1"}, "SK": {"S": "META"}}
    assert check["ExpressionAttributeValues"] == {":running": {"S": "running"}}


def test_discovery_writes_company_and_pin_with_valid_wire_keys(monkeypatch, wire_requests):
    company = Company(
        place_id="p1", name="Cafe", address="Melbourne", roles=["chef"],
        lat=-33.87, lng=151.21, country_code="au",
    )
    monkeypatch.setattr(handlers, "discover", lambda **_kwargs: SimpleNamespace(
        companies=[company], stats={},
    ))
    result = handlers._discover({
        "search_id": "s1", "lat": -33.87, "lng": 151.21, "radius_km": 5,
        "roles": [{"label": "chef", "curated_key": None}],
    })

    assert result["companies"] == [company.model_dump()]
    records, trace = _transactions(wire_requests)
    _assert_running_check(records[0])
    item = records[1]["Put"]["Item"]
    assert item["PK"] == {"S": "SEARCH#s1"}
    assert item["SK"] == {"S": "RESULT#p1"}
    assert item["links"] == {"L": []}
    pin = records[2]["Put"]["Item"]
    assert pin["SK"] == {"S": "PIN#p1"}
    assert pin["lat"] == {"S": "-33.87"}
    assert "N" in pin["expires_at"]
    _assert_running_check(trace[0])


def test_trace_write_keeps_scalar_keys_and_numeric_expiry(wire_requests):
    handlers._put_step("s1", TraceStep(
        tag=Tag.CHECKING, tool="fetch_url", place_id="p1", text="Cafe",
        at="2026-10-02T00:00:00+00:00",
    ))

    check, put = _transactions(wire_requests)[0]
    _assert_running_check(check)
    item = put["Put"]["Item"]
    assert item["SK"] == {"S": "STEP#2026-10-02T00:00:00+00:00#p1"}
    assert item["tool"] == {"S": "fetch_page"}
    assert "N" in item["expires_at"]


def test_investigation_writes_native_lists_and_stats_once(monkeypatch, wire_requests):
    monkeypatch.setattr(handlers, "_search_stopped", lambda _sid: False)
    monkeypatch.setattr(handlers.observability, "flush", lambda: None)
    monkeypatch.setattr(handlers, "investigate", lambda *_args, **_kwargs: SimpleNamespace(
        findings=Findings(
            opportunity_type=OpportunityType.CAREERS_PAGE,
            links=["https://example.com/careers"], evidence="Careers page found",
            confidence=0.9,
        ),
        cancelled=False, stats=lambda: {"tool_calls": 1}, tool_calls=1,
        metered_calls={}, input_tokens=0, output_tokens=0, error=None,
    ))
    result = handlers.investigate_handler({
        "search_id": "s1", "company": {
            "place_id": "p1", "name": "Cafe", "address": "Melbourne", "roles": ["chef"],
        },
    })

    assert result["outcome"] == "success"
    check, update = _transactions(wire_requests)[0]
    _assert_running_check(check)
    assert update["Update"]["Key"]["SK"] == {"S": "RESULT#p1"}
    values = update["Update"]["ExpressionAttributeValues"]
    assert values[":l"] == {"L": [{"S": "https://example.com/careers"}]}
    assert values[":st"] == {"M": {"tool_calls": {"S": "1"}}}
