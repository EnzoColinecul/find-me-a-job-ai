"""Unit test for the idempotent user upsert using a fake DynamoDB table."""
import app.users as users


class FakeTable:
    def __init__(self) -> None:
        self.store: dict = {}

    def put_item(self, Item, ConditionExpression=None):  # noqa: N803
        key = (Item["PK"], Item["SK"])
        if ConditionExpression and key in self.store:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem"
            )
        self.store[key] = Item

    def get_item(self, Key):  # noqa: N803
        return {"Item": self.store[(Key["PK"], Key["SK"])]}


def test_ensure_user_idempotent(monkeypatch) -> None:
    fake = FakeTable()
    monkeypatch.setattr(users, "_get_table", lambda: fake)

    first = users.ensure_user("abc", "a@example.com", "Ada")
    assert first["free_search_used"] is False
    assert first["email"] == "a@example.com"

    # second call must not overwrite, returns stored record
    again = users.ensure_user("abc", "a@example.com", "Ada")
    assert again["PK"] == "USER#abc"
    assert len(fake.store) == 1
