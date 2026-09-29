"""Start search workflows from the durable DynamoDB META insert stream."""
import json
import logging
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
_table = None
_sfn = None
_deserializer = TypeDeserializer()
_serializer = TypeSerializer()


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource(
            "dynamodb", region_name=os.environ.get("FMAJ_AWS_REGION", "ap-southeast-2")
        ).Table(os.environ["FMAJ_TABLE_NAME"])
    return _table


def _get_sfn():
    global _sfn
    if _sfn is None:
        _sfn = boto3.client(
            "stepfunctions", region_name=os.environ.get("FMAJ_AWS_REGION", "ap-southeast-2")
        )
    return _sfn


def _plain(item: dict) -> dict:
    return {key: _deserializer.deserialize(value) for key, value in item.items()}


def _compensate_permanent_start_failure(meta: dict) -> None:
    """Fail the pending search and refund its reservations in one transaction."""
    sub = str(meta["user_sub"])
    search_id = str(meta["search_id"])
    month = datetime.fromisoformat(str(meta["created_at"])).strftime("%Y-%m")
    table_name = os.environ["FMAJ_TABLE_NAME"]

    def value(item):
        return _serializer.serialize(item)

    actions = [{"Update": {
        "TableName": table_name,
        "Key": {"PK": value(meta["PK"]), "SK": value("META")},
        "UpdateExpression": (
            "SET #s = :failed, execution_start_state = :start_failed, "
            "error_code = :error_code, retryable = :retryable, failed_at = :at"
        ),
        "ConditionExpression": "#s = :pending AND execution_start_state = :start_pending",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {k: value(v) for k, v in {
            ":failed": "failed", ":start_failed": "failed", ":error_code": "workflow_start_failed",
            ":retryable": False, ":at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
            ":pending": "pending", ":start_pending": "pending",
        }.items()},
    }}, {"Update": {
        "TableName": table_name,
        "Key": {"PK": value(f"USER#{sub}"), "SK": value("PROFILE")},
        "UpdateExpression": "SET free_search_used = :unused, active_since = :empty, active_search_id = :empty",
        "ConditionExpression": "free_search_used = :used AND active_search_id = :sid",
        "ExpressionAttributeValues": {k: value(v) for k, v in {
            ":unused": False, ":empty": "", ":used": True, ":sid": search_id,
        }.items()},
    }}]
    if int(os.environ.get("FMAJ_GLOBAL_MONTHLY_SEARCHES", "30")):
        actions.append({"Update": {
            "TableName": table_name,
            "Key": {"PK": value("SYSTEM#QUOTA"), "SK": value(f"MONTH#{month}")},
            "UpdateExpression": "ADD #c :minus",
            "ConditionExpression": "#c > :zero",
            "ExpressionAttributeNames": {"#c": "count"},
            "ExpressionAttributeValues": {k: value(v) for k, v in {
                ":minus": -1, ":zero": 0,
            }.items()},
        }})
    _get_table().meta.client.transact_write_items(TransactItems=actions)


_PERMANENT_START_ERRORS = {
    "AccessDeniedException", "InvalidArn", "InvalidExecutionInput",
    "KmsAccessDeniedException", "KmsInvalidStateException",
    "StateMachineDoesNotExist", "StateMachineDeleting", "ValidationException",
}


def handler(event: dict, _context=None) -> dict:
    """Start each pending search; stream retries make an ambiguous start safe."""
    started = 0
    for record in event.get("Records", []):
        if record.get("eventName") != "INSERT":
            continue
        image = record.get("dynamodb", {}).get("NewImage")
        if not image:
            continue
        meta = _plain(image)
        if meta.get("SK") != "META" or not str(meta.get("PK", "")).startswith("SEARCH#"):
            continue
        if meta.get("status") != "pending" or meta.get("execution_arn"):
            continue
        search_id = str(meta["search_id"])
        current = _get_table().get_item(
            Key={"PK": meta["PK"], "SK": "META"}, ConsistentRead=True
        ).get("Item") or {}
        if current.get("status") not in {"pending", "running"} or current.get("execution_arn"):
            continue

        try:
            execution = _get_sfn().start_execution(
                stateMachineArn=os.environ["FMAJ_STATE_MACHINE_ARN"],
                name=f"search-{search_id}",
                input=json.dumps({
                    "search_id": search_id,
                    "lat": float(meta["lat"]),
                    "lng": float(meta["lng"]),
                    "radius_km": float(meta["radius_km"]),
                    "roles": meta["roles"],
                }),
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in _PERMANENT_START_ERRORS:
                raise
            logger.error("workflow start failed permanently for %s (%s)", search_id, code)
            _compensate_permanent_start_failure(meta)
            continue
        try:
            _get_table().update_item(
                Key={"PK": meta["PK"], "SK": "META"},
                UpdateExpression=(
                    "SET execution_arn = :arn, execution_start_state = :started, "
                    "execution_started_at = :at"
                ),
                ConditionExpression=(
                    "#s IN (:pending, :running) AND execution_start_state = :start_pending"
                ),
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":arn": execution["executionArn"],
                    ":started": "started",
                    ":at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
                    ":pending": "pending",
                    ":running": "running",
                    ":start_pending": "pending",
                },
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            # A fast workflow may already have transitioned the META row. Its
            # state is authoritative; do not fail and replay a completed search.
        started += 1
    return {"started": started}
