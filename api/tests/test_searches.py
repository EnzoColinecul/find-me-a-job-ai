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

    def get_item(self, Key):  # noqa: N803
        item = self.store.get((Key["PK"], Key["SK"]))
        return {"Item": item} if item else {}

    def update_item(  # noqa: N803
        self,
        Key,
        UpdateExpression,
        ExpressionAttributeValues,
        ConditionExpression=None,
        ExpressionAttributeNames=None,
    ):
        item = self.store.get((Key["PK"], Key["SK"]))

        if ConditionExpression is not None:
            # emulate: attribute_exists(PK) AND free_search_used = :f
            if item is None or item.get("free_search_used") is not False:
                raise ClientError(
                    {"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem"
                )
            item["free_search_used"] = True
            return

        # Unconditional SET: apply "SET a = :x, b = :y" against the item, mapping
        # #name placeholders back to real attribute names.
        if item is None:
            item = {"PK": Key["PK"], "SK": Key["SK"]}
            self.store[(Key["PK"], Key["SK"])] = item
        names = ExpressionAttributeNames or {}
        for clause in UpdateExpression.removeprefix("SET ").split(","):
            attr, _, placeholder = clause.strip().partition(" = ")
            item[names.get(attr, attr)] = ExpressionAttributeValues[placeholder.strip()]

    def query(  # noqa: N803
        self,
        KeyConditionExpression,
        ExpressionAttributeValues=None,
        ScanIndexForward=True,
        Limit=None,
    ):
        """Supports both call styles: the raw "PK = :pk" string used by get_search,
        and the boto3 Key() condition objects used by list_searches."""
        if ExpressionAttributeValues is not None:
            pk = ExpressionAttributeValues[":pk"]
            prefix = ""
        else:
            values = KeyConditionExpression.get_expression()["values"]
            pk = values[0].get_expression()["values"][1]
            prefix = values[1].get_expression()["values"][1]

        items = [
            v
            for (p, s), v in self.store.items()
            if p == pk and s.startswith(prefix)
        ]
        items.sort(key=lambda i: i["SK"], reverse=not ScanIndexForward)
        if Limit is not None:
            items = items[:Limit]
        return {"Items": items}


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


def test_list_searches_newest_first_and_owner_scoped(table, monkeypatch) -> None:
    from app.settings import settings

    # The free-search quota caps a real user at one search, so lift it here to
    # exercise ordering the way a subscribed user would see it.
    monkeypatch.setattr(settings, "max_roles", 3)
    _user(table)
    _user(table, sub="u2")

    for role, label in [("chef", "Surry Hills"), ("barista", "Newtown")]:
        table.store[("USER#u1", "PROFILE")]["free_search_used"] = False
        searches.create_search(
            "u1",
            SearchRequest(**{**VALID, "roles": [role], "location_label": label}),
        )
    searches.create_search(
        "u2", SearchRequest(**{**VALID, "roles": ["retail assistant"]})
    )

    mine = searches.list_searches("u1")
    assert [s["roles"] for s in mine] == [["barista"], ["chef"]]  # newest first
    assert mine[0]["location_label"] == "Newtown"
    assert len(searches.list_searches("u2")) == 1
    assert searches.list_searches("nobody") == []


def test_list_searches_respects_limit(table) -> None:
    _user(table)
    for _ in range(3):
        table.store[("USER#u1", "PROFILE")]["free_search_used"] = False
        searches.create_search("u1", SearchRequest(**VALID))
    assert len(searches.list_searches("u1", limit=2)) == 2


def test_profile_item_is_not_listed_as_a_search(table) -> None:
    """USER#<sub> holds PROFILE alongside the search index — don't confuse them."""
    _user(table)
    searches.create_search("u1", SearchRequest(**VALID))
    assert len(searches.list_searches("u1")) == 1


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


# ---- trace steps, progress and Stop -----------------------------------------


def _step(table, sid, at, tag="checking", tool="fetch_page", text="Cafe X", meta=""):
    table.store[(f"SEARCH#{sid}", f"STEP#{at}#p1")] = {
        "PK": f"SEARCH#{sid}",
        "SK": f"STEP#{at}#p1",
        "tag": tag,
        "tool": tool,
        "text": text,
        "meta": meta,
        "at": at,
    }


def test_steps_come_back_in_chronological_order(table) -> None:
    _user(table)
    sid = searches.create_search("u1", SearchRequest(**VALID))["search_id"]
    # Inserted out of order on purpose.
    _step(table, sid, "2026-08-04T10:00:02", tool="fetch_page")
    _step(table, sid, "2026-08-04T10:00:01", tag="searching", tool="places.nearby")
    _step(table, sid, "2026-08-04T10:00:03", tag="found", tool="extract_contact")

    steps = searches.get_search("u1", sid)["steps"]
    assert [s["tool"] for s in steps] == [
        "places.nearby",
        "fetch_page",
        "extract_contact",
    ]


def test_steps_are_not_mistaken_for_results(table) -> None:
    """STEP# and RESULT# share the search partition — they must stay separate."""
    _user(table)
    sid = searches.create_search("u1", SearchRequest(**VALID))["search_id"]
    _step(table, sid, "2026-08-04T10:00:01")
    found = searches.get_search("u1", sid)
    assert found["total"] == 0
    assert found["results"] == []
    assert len(found["steps"]) == 1


def test_progress_counts_only_investigated_companies(table) -> None:
    _user(table)
    sid = searches.create_search("u1", SearchRequest(**VALID))["search_id"]
    table.store[(f"SEARCH#{sid}", "META")]["company_count"] = 3
    for i, otype in enumerate(["careers_page", "pending", "none"]):
        table.store[(f"SEARCH#{sid}", f"RESULT#p{i}")] = {
            "PK": f"SEARCH#{sid}",
            "SK": f"RESULT#p{i}",
            "opportunity_type": otype,
        }
    # 2 of 3 finished: "pending" hasn't been investigated yet, but "none" has —
    # a company the agent checked and rejected is still progress.
    assert searches.get_search("u1", sid)["progress"] == {"done": 2, "total": 3}


def test_progress_total_is_zero_before_discovery_reports(table) -> None:
    """Don't guess the denominator from partial results — say we don't know."""
    _user(table)
    sid = searches.create_search("u1", SearchRequest(**VALID))["search_id"]
    assert searches.get_search("u1", sid)["progress"] == {"done": 0, "total": 0}


def test_stop_marks_cancelled_and_halts_the_execution(table, monkeypatch) -> None:
    _user(table)
    sid = searches.create_search("u1", SearchRequest(**VALID))["search_id"]
    table.store[(f"SEARCH#{sid}", "META")]["execution_arn"] = "arn:aws:states:::exec/x"

    stopped: list = []
    monkeypatch.setattr(
        searches,
        "_get_sfn",
        lambda: type("S", (), {"stop_execution": lambda _s, **kw: stopped.append(kw)})(),
    )

    assert searches.stop_search("u1", sid)["status"] == "cancelled"
    assert stopped and stopped[0]["executionArn"] == "arn:aws:states:::exec/x"
    assert searches.get_search("u1", sid)["status"] == "cancelled"


def test_stop_is_rejected_once_the_search_has_finished(table) -> None:
    _user(table)
    sid = searches.create_search("u1", SearchRequest(**VALID))["search_id"]
    table.store[(f"SEARCH#{sid}", "META")]["status"] = "completed"
    with pytest.raises(searches.NotStoppable):
        searches.stop_search("u1", sid)


def test_stop_still_cancels_when_the_execution_is_already_gone(table, monkeypatch) -> None:
    """The pipeline may not be deployed, or the execution already ended. The user
    asked for it to stop — don't leave it 'running' forever."""
    _user(table)
    sid = searches.create_search("u1", SearchRequest(**VALID))["search_id"]
    table.store[(f"SEARCH#{sid}", "META")]["execution_arn"] = "arn:bad"

    def boom(**_kw):
        raise ClientError({"Error": {"Code": "ExecutionDoesNotExist"}}, "StopExecution")

    monkeypatch.setattr(
        searches,
        "_get_sfn",
        lambda: type("S", (), {"stop_execution": lambda _s, **kw: boom(**kw)})(),
    )
    assert searches.stop_search("u1", sid)["status"] == "cancelled"


def test_stop_refuses_someone_elses_search(table) -> None:
    _user(table)
    sid = searches.create_search("u1", SearchRequest(**VALID))["search_id"]
    assert searches.stop_search("someone-else", sid) is None
