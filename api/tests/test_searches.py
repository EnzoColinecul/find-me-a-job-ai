import pytest
from botocore.exceptions import ClientError
from pydantic import ValidationError

import app.searches as searches
from app.searches import QuotaExhausted, SearchRequest


class FakeTable:
    """Minimal DynamoDB table fake: put/update with conditions, PK query."""

    def __init__(self) -> None:
        self.store: dict = {}

    def put_item(self, Item, ConditionExpression=None):  # noqa: N803
        self.store[(Item["PK"], Item["SK"])] = Item

    def update_item(self, Key, UpdateExpression, ConditionExpression, ExpressionAttributeValues):  # noqa: N803
        item = self.store.get((Key["PK"], Key["SK"]))
        # emulate: attribute_exists(PK) AND free_search_used = :f
        if item is None or item.get("free_search_used") is not False:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem"
            )
        item["free_search_used"] = True

    def query(self, KeyConditionExpression, ExpressionAttributeValues):  # noqa: N803
        pk = ExpressionAttributeValues[":pk"]
        return {"Items": [v for (p, _), v in self.store.items() if p == pk]}


@pytest.fixture()
def table(monkeypatch):
    fake = FakeTable()
    monkeypatch.setattr(searches, "_get_table", lambda: fake)
    return fake


def _user(table, sub="u1", used=False):
    table.store[(f"USER#{sub}", "PROFILE")] = {
        "PK": f"USER#{sub}",
        "SK": "PROFILE",
        "free_search_used": used,
    }


VALID = dict(lat=-33.87, lng=151.21, radius_km=5, roles=["chef"])


def test_validation_rejects_outside_australia() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(lat=51.5, lng=-0.12, radius_km=5, roles=["chef"])  # London


def test_validation_rejects_big_radius() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(**{**VALID, "radius_km": 50})


def test_role_cap_is_config_driven(monkeypatch) -> None:
    """max_roles is a single knob — raising it must not need code changes."""
    from app.settings import settings

    monkeypatch.setattr(settings, "max_roles", 1)
    with pytest.raises(ValidationError):
        SearchRequest(**{**VALID, "roles": ["chef", "barista"]})

    monkeypatch.setattr(settings, "max_roles", 3)
    req = SearchRequest(**{**VALID, "roles": ["chef", "barista"]})
    assert [r.label for r in req.roles] == ["chef", "barista"]


def test_roles_accept_strings_and_specs() -> None:
    plain = SearchRequest(**VALID)
    assert plain.roles[0].label == "chef" and plain.roles[0].curated_key is None

    spec = SearchRequest(**{**VALID,
                            "roles": [{"label": "Dishwasher",
                                       "curated_key": "kitchen hand"}]})
    assert spec.roles[0].label == "dishwasher"  # normalized
    assert spec.roles[0].curated_key == "kitchen hand"


def test_duplicate_roles_deduped() -> None:
    req = SearchRequest(**{**VALID, "roles": ["Chef", "chef"]})
    assert len(req.roles) == 1


def test_create_search_consumes_quota(table) -> None:
    _user(table)
    meta = searches.create_search("u1", SearchRequest(**VALID))
    assert meta["status"] == "pending"
    assert table.store[("USER#u1", "PROFILE")]["free_search_used"] is True


def test_second_search_rejected(table) -> None:
    _user(table)
    searches.create_search("u1", SearchRequest(**VALID))
    with pytest.raises(QuotaExhausted):
        searches.create_search("u1", SearchRequest(**VALID))


def test_get_search_owner_only(table) -> None:
    _user(table)
    meta = searches.create_search("u1", SearchRequest(**VALID))
    sid = meta["search_id"]

    mine = searches.get_search("u1", sid)
    assert mine is not None and mine["status"] == "pending"
    assert searches.get_search("intruder", sid) is None
    assert searches.get_search("u1", "nope") is None


def test_get_search_includes_results(table) -> None:
    _user(table)
    meta = searches.create_search("u1", SearchRequest(**VALID))
    sid = meta["search_id"]
    table.store[(f"SEARCH#{sid}", "RESULT#place1")] = {
        "PK": f"SEARCH#{sid}",
        "SK": "RESULT#place1",
        "company": "Cafe X",
        "opportunity_type": "careers_page",
        "links": ["https://cafex.com.au/careers"],
    }
    found = searches.get_search("u1", sid)
    assert found["total"] == 1
    assert found["results"][0]["company"] == "Cafe X"
