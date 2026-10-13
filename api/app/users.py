"""User records in the DynamoDB single table.

Item shape:
  PK = USER#<sub>, SK = PROFILE
  email, name, free_search_used (bool), created_at
"""
import hashlib
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from app.settings import settings

_table = None


def _get_table():
    global _table
    if _table is None:
        session = boto3.Session(
            profile_name=settings.aws_profile or None, region_name=settings.aws_region
        )
        _table = session.resource("dynamodb").Table(settings.table_name)
    return _table


def ensure_user(sub: str, email: str, name: str | None) -> dict:
    """Create the user on first sign-in (idempotent), then return the profile item."""
    table = _get_table()
    now = datetime.now(timezone.utc).isoformat()  # noqa: UP017 — Python 3.10 tooling compatibility
    item = {
        "PK": f"USER#{sub}",
        "SK": "PROFILE",
        "email": email,
        "name": name or "",
        "free_search_used": False,
        "created_at": now,
    }
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
        return item
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        # already exists -> return stored record
        resp = table.get_item(Key={"PK": f"USER#{sub}", "SK": "PROFILE"})
        return resp["Item"]


def reserve_interpretation(sub: str, client_ip: str | None = None) -> bool:
    """Atomically cap billed role interpretation by user and forwarded client IP."""
    now = datetime.now(timezone.utc)  # noqa: UP017 — Python 3.10 tooling compatibility
    window = now.strftime("%Y%m%dT%H%M")
    expires = int(now.timestamp()) + 120
    keys = [(f"USER#{sub}", f"INTERPRET#{window}")]
    if client_ip:
        ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:24]
        keys.append((f"INTERPRET_IP#{ip_hash}", window))
    for pk, sk in keys:
        try:
            _get_table().update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression="SET expires_at = :ttl ADD request_count :one",
                ConditionExpression="attribute_not_exists(request_count) OR request_count < :cap",
                ExpressionAttributeValues={
                    ":ttl": expires, ":one": 1, ":cap": settings.interpret_requests_per_minute,
                },
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
    return True
