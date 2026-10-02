"""Check transaction payloads after the real SDK's resource transformations."""
import json

import boto3
import pytest
from botocore.awsrequest import AWSResponse

from app import reconciler, searches


@pytest.fixture
def transaction_requests():
    resource = boto3.resource(
        "dynamodb", region_name="ap-southeast-2",
        aws_access_key_id="testing", aws_secret_access_key="testing",
    )
    requests = []

    def capture(params, **_kwargs):
        requests.append(json.loads(params["body"]))
        # Stop at the serialized request boundary: no network or AWS writes.
        return AWSResponse("https://offline.invalid", 200, {}, None), {}

    resource.meta.client.meta.events.register(
        "before-call.dynamodb.TransactWriteItems", capture,
    )
    return resource.Table("table"), requests


def test_reservation_serializes_numbers_keys_and_nested_records_once(
    monkeypatch, transaction_requests,
):
    table, requests = transaction_requests
    monkeypatch.setattr(searches, "_get_table", lambda: table)
    monkeypatch.setattr(searches.settings, "table_name", "table")
    monkeypatch.setattr(searches.settings, "global_monthly_searches", 30)
    searches._transact_search_reservation(
        sub="u1", req=searches.SearchRequest(
            lat=-33.87, lng=151.21, radius_km=5, roles=["chef"],
        ),
        search_id="search123", key_hash="key123", month="2026-10",
        now="2026-10-02T00:00:00+00:00", expected_since="", expected_id="",
    )

    actions = requests[0]["TransactItems"]
    profile = actions[0]["Update"]
    assert profile["Key"]["PK"] == {"S": "USER#u1"}
    assert profile["ExpressionAttributeValues"][":used"] == {"BOOL": True}
    counter = actions[1]["Update"]
    assert counter["ExpressionAttributeValues"][":one"] == {"N": "1"}
    assert counter["ExpressionAttributeValues"][":cap"] == {"N": "30"}
    meta = actions[2]["Put"]["Item"]
    assert meta["roles"]["L"][0]["M"]["label"] == {"S": "chef"}
    assert meta["roles"]["L"][0]["M"]["curated_key"] == {"NULL": True}
    assert actions[3]["Put"]["Item"]["roles"] == {"L": [{"S": "chef"}]}
    assert "N" in actions[4]["Put"]["Item"]["expires_at"]


def test_refund_serializes_decrement_and_profile_values_once(
    monkeypatch, transaction_requests,
):
    table, requests = transaction_requests
    monkeypatch.setattr(reconciler, "_get_table", lambda: table)
    monkeypatch.setenv("FMAJ_TABLE_NAME", "table")
    monkeypatch.setenv("FMAJ_GLOBAL_MONTHLY_SEARCHES", "30")
    reconciler._compensate_permanent_start_failure({
        "PK": "SEARCH#search123", "search_id": "search123", "user_sub": "u1",
        "created_at": "2026-10-02T00:00:00+00:00",
    })

    actions = requests[0]["TransactItems"]
    assert actions[0]["Update"]["Key"]["PK"] == {"S": "SEARCH#search123"}
    assert actions[1]["Update"]["ExpressionAttributeValues"][":unused"] == {"BOOL": False}
    assert actions[2]["Update"]["ExpressionAttributeValues"][":minus"] == {"N": "-1"}
