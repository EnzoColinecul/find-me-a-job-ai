"""Search creation and retrieval.

Table items:
  SEARCH#<id> / META                       — params, status, owner, counts
  SEARCH#<id> / RESULT#<place_id>          — written incrementally by the pipeline
  USER#<sub> / SEARCH#<created_at>#<id>    — owner index, for the workspace rail
Status: pending -> running -> completed | failed

The owner index is the adjacency-list pattern rather than a GSI: listing a user's
searches is then a plain query on their own partition, with no extra provisioned
capacity and no infra change. It deliberately stores only descriptive fields (roles,
location, radius) and NOT status — status lives on META and would go stale here,
and the rail links straight through to the search page, which polls it live.
"""
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field, field_validator, model_validator

from app.settings import settings

# No market restriction: anyone, anywhere can run a search. Coordinates are only
# sanity-checked against the globe, which still catches a swapped lat/lng or a
# malformed payload without deciding where a user is allowed to live.
#
# There WAS an Australia bounding box here while V1 was AU-only. Removed
# deliberately (2026-08-15) so the beta can be tested from any country — the
# country-specific parts now live in the agent, which reads the country off the
# Places result and picks a job board that covers it (fmaj_agent.tools.impl).
# Don't reintroduce a geographic gate here; gate on plan/quota instead.
LAT_RANGE = (-90.0, 90.0)
LNG_RANGE = (-180.0, 180.0)


class RoleSpec(BaseModel):
    """A role to search for. `curated_key` borrows venue types from a known role."""

    label: str
    curated_key: str | None = None


class SearchRequest(BaseModel):
    lat: float
    lng: float
    radius_km: float = Field(gt=0)
    # Free-text the user typed, kept for analytics/eval (what did they ask for vs
    # what did the LLM propose vs what did they confirm).
    query_text: str | None = None
    # Human-readable place the user picked ("Surry Hills NSW 2010"), for the
    # workspace's recent-searches rail. Coordinates are the source of truth.
    location_label: str | None = Field(default=None, max_length=200)
    roles: list[RoleSpec] = Field(min_length=1)

    @field_validator("roles", mode="before")
    @classmethod
    def _coerce_roles(cls, v):
        """Accept ["chef"] as well as [{"label": "chef", "curated_key": ...}]."""
        if isinstance(v, list):
            return [{"label": r} if isinstance(r, str) else r for r in v]
        return v

    @model_validator(mode="after")
    def _within_limits(self):
        if len(self.roles) > settings.max_roles:
            raise ValueError(
                f"At most {settings.max_roles} role(s) per search on your current plan"
            )
        if self.radius_km > settings.max_radius_km:
            raise ValueError(f"Radius must be <= {settings.max_radius_km} km")
        return self

    @field_validator("lat")
    @classmethod
    def _lat_on_earth(cls, v: float) -> float:
        if not LAT_RANGE[0] <= v <= LAT_RANGE[1]:
            raise ValueError("Latitude must be between -90 and 90")
        return v

    @field_validator("lng")
    @classmethod
    def _lng_on_earth(cls, v: float) -> float:
        if not LNG_RANGE[0] <= v <= LNG_RANGE[1]:
            raise ValueError("Longitude must be between -180 and 180")
        return v

    @field_validator("roles")
    @classmethod
    def _clean_roles(cls, v: list[RoleSpec]) -> list[RoleSpec]:
        cleaned, seen = [], set()
        for r in v:
            label = r.label.strip().lower()
            if label and label not in seen:
                seen.add(label)
                cleaned.append(RoleSpec(label=label, curated_key=r.curated_key))
        if not cleaned:
            raise ValueError("At least one role required")
        return cleaned


class QuotaExhausted(Exception):
    """This user's free search is gone."""


class MonthlyCapReached(Exception):
    """The whole PoC has run its budgeted number of searches for the month."""


class SearchInProgress(Exception):
    """This user already has a search running."""


logger = logging.getLogger(__name__)

_table = None
_sfn = None
_serializer = TypeSerializer()


def _session() -> boto3.Session:
    return boto3.Session(
        profile_name=settings.aws_profile or None, region_name=settings.aws_region
    )


def _get_table():
    global _table
    if _table is None:
        _table = _session().resource("dynamodb").Table(settings.table_name)
    return _table


def _get_sfn():
    global _sfn
    if _sfn is None:
        _sfn = _session().client("stepfunctions")
    return _sfn


def _month_key(when: datetime | None = None) -> str:
    return (when or datetime.now(timezone.utc)).strftime("%Y-%m")  # noqa: UP017 — Python 3.10 tooling compatibility


TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _search_is_finished(search_id: str) -> bool:
    """True if the named search is over — or gone, which amounts to the same."""
    if not search_id:
        return True
    item = _get_table().get_item(
        Key={"PK": f"SEARCH#{search_id}", "SK": "META"}, ConsistentRead=True
    ).get("Item")
    if item is None:
        return True
    return item.get("status") in TERMINAL_STATUSES


def _check_search_lease(sub: str) -> tuple[str, str]:
    """Read the lease snapshot that the reservation transaction must compare.

    Two independent ways the slot frees up, because relying on either alone is
    broken:

    - **The named search reached a terminal status.** This is the normal path
      and it's immediate. A pure time lease would make someone wait out the
      clock after their search had visibly finished, which is indefensible.
    - **The lease aged out.** The backstop for a search that never reaches a
      terminal status at all — a crashed Lambda, an undeployed pipeline. Without
      it a user could be locked out permanently by a bug, with nothing in the
      product able to release them.

    Deliberately *not* a flag some other process clears: the only candidate for
    that job is the pipeline, and the pipeline failing is exactly the case the
    guard has to survive.
    """
    now = datetime.now(timezone.utc)  # noqa: UP017 — Python 3.10 tooling compatibility
    cutoff = (now - timedelta(minutes=settings.search_lease_minutes)).isoformat()

    profile = _get_table().get_item(
        Key={"PK": f"USER#{sub}", "SK": "PROFILE"}, ConsistentRead=True
    ).get("Item") or {}
    held_since = profile.get("active_since") or ""
    held_id = profile.get("active_search_id") or ""

    # ISO-8601 UTC strings sort lexicographically, so this is a real comparison.
    if held_since >= cutoff and not _search_is_finished(held_id):
        raise SearchInProgress

    return held_since, held_id


def _ddb_value(value):
    return _serializer.serialize(value)


def _transact_search_reservation(
    *, sub: str, req: SearchRequest, search_id: str, key_hash: str,
    month: str, now: str, expected_since: str, expected_id: str,
) -> dict:
    """Atomically reserve quota/lease and persist every durable search record."""
    meta = {
        "PK": f"SEARCH#{search_id}", "SK": "META", "search_id": search_id,
        "user_sub": sub, "lat": str(req.lat), "lng": str(req.lng),
        "radius_km": str(req.radius_km),
        "roles": [r.model_dump() for r in req.roles],
        "query_text": req.query_text or "", "location_label": req.location_label or "",
        "status": "pending", "created_at": now,
        "observability_trace_id": _trace_id(search_id),
        "execution_start_state": "pending",
    }
    owner_index = {
        "PK": f"USER#{sub}", "SK": f"SEARCH#{now}#{search_id}",
        "search_id": search_id, "roles": [r.label for r in req.roles],
        "location_label": req.location_label or "", "lat": str(req.lat),
        "lng": str(req.lng), "radius_km": str(req.radius_km), "created_at": now,
    }
    actions = [{"Update": {
        "TableName": settings.table_name,
        "Key": {"PK": _ddb_value(f"USER#{sub}"), "SK": _ddb_value("PROFILE")},
        "UpdateExpression": (
            "SET free_search_used = :used, active_since = :now, active_search_id = :sid"
        ),
        "ConditionExpression": (
            "attribute_exists(PK) AND free_search_used = :unused AND "
            "((attribute_not_exists(active_since) AND attribute_not_exists(active_search_id)) "
            "OR (active_since = :expected_since AND "
            "(attribute_not_exists(active_search_id) OR active_search_id = :expected_id)))"
        ),
        "ExpressionAttributeValues": {k: _ddb_value(v) for k, v in {
            ":used": True, ":unused": False, ":now": now, ":sid": search_id,
            ":expected_since": expected_since, ":expected_id": expected_id,
        }.items()},
    }}]
    if settings.global_monthly_searches:
        actions.append({"Update": {
            "TableName": settings.table_name,
            "Key": {"PK": _ddb_value("SYSTEM#QUOTA"), "SK": _ddb_value(f"MONTH#{month}")},
            "UpdateExpression": "ADD #c :one",
            "ConditionExpression": "attribute_not_exists(#c) OR #c < :cap",
            "ExpressionAttributeNames": {"#c": "count"},
            "ExpressionAttributeValues": {k: _ddb_value(v) for k, v in {
                ":one": 1, ":cap": settings.global_monthly_searches,
            }.items()},
        }})
    for item in (meta, owner_index):
        actions.append({"Put": {
            "TableName": settings.table_name,
            "Item": {k: _ddb_value(v) for k, v in item.items()},
            "ConditionExpression": "attribute_not_exists(PK)",
        }})
    if key_hash:
        idem = {
            "PK": f"USER#{sub}", "SK": f"IDEMPOTENCY#{key_hash}",
            "search_id": search_id,
            "expires_at": int(datetime.now(timezone.utc).timestamp()) + 7 * 24 * 3600,  # noqa: UP017 — Python 3.10 tooling compatibility
        }
        actions.append({"Put": {
            "TableName": settings.table_name,
            "Item": {k: _ddb_value(v) for k, v in idem.items()},
            "ConditionExpression": "attribute_not_exists(PK)",
        }})
    _get_table().meta.client.transact_write_items(
        TransactItems=actions, ClientRequestToken=search_id,
    )
    return meta


def _reservation_failed(sub: str, month: str, held_since: str, held_id: str) -> None:
    """Translate transaction condition failures into stable API errors."""
    now = datetime.now(timezone.utc)  # noqa: UP017 — Python 3.10 tooling compatibility
    cutoff = (now - timedelta(minutes=settings.search_lease_minutes)).isoformat()
    profile = _get_table().get_item(
        Key={"PK": f"USER#{sub}", "SK": "PROFILE"}, ConsistentRead=True
    ).get("Item") or {}
    active_since = profile.get("active_since") or ""
    active_id = profile.get("active_search_id") or ""
    if (active_since >= cutoff and not _search_is_finished(active_id)) or (
        held_since >= cutoff and not _search_is_finished(held_id)
    ):
        raise SearchInProgress
    if settings.global_monthly_searches:
        counter = _get_table().get_item(
            Key={"PK": "SYSTEM#QUOTA", "SK": f"MONTH#{month}"}, ConsistentRead=True
        ).get("Item") or {}
        if int(counter.get("count", 0)) >= settings.global_monthly_searches:
            raise MonthlyCapReached
    if profile.get("free_search_used") is not False:
        raise QuotaExhausted
    raise SearchInProgress


def _release_search_lease(sub: str, search_id: str) -> None:
    """Free the concurrency slot early, rather than waiting for the lease out."""
    try:
        _get_table().update_item(
            Key={"PK": f"USER#{sub}", "SK": "PROFILE"},
            UpdateExpression="SET active_since = :none, active_search_id = :none",
            ConditionExpression="active_search_id = :sid",
            ExpressionAttributeValues={":none": "", ":sid": search_id},
        )
    except ClientError as exc:
        logger.warning("could not release search lease for %s: %s", sub, exc)


def create_search(sub: str, req: SearchRequest, idempotency_key: str | None = None) -> dict:
    """Atomically reserve quota/lease and persist a search for stream dispatch."""
    if idempotency_key:
        key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
        existing = _get_table().get_item(
            Key={"PK": f"USER#{sub}", "SK": f"IDEMPOTENCY#{key_hash}"}, ConsistentRead=True
        ).get("Item")
        if existing:
            prior = _get_table().get_item(
                Key={"PK": f"SEARCH#{existing['search_id']}", "SK": "META"},
                ConsistentRead=True,
            ).get("Item")
            if prior and prior.get("user_sub") == sub:
                return prior
    else:
        key_hash = ""

    search_id = uuid.uuid4().hex[:12]
    held_since, held_id = _check_search_lease(sub)
    month = _month_key()
    now = datetime.now(timezone.utc).isoformat()  # noqa: UP017 — Python 3.10 tooling compatibility
    try:
        meta = _transact_search_reservation(
            sub=sub, req=req, search_id=search_id, key_hash=key_hash,
            month=month, now=now, expected_since=held_since, expected_id=held_id,
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "TransactionCanceledException":
            raise
        if key_hash:
            existing = _get_table().get_item(
                Key={"PK": f"USER#{sub}", "SK": f"IDEMPOTENCY#{key_hash}"},
                ConsistentRead=True,
            ).get("Item")
            if existing:
                prior = _get_table().get_item(
                    Key={"PK": f"SEARCH#{existing['search_id']}", "SK": "META"},
                    ConsistentRead=True,
                ).get("Item")
                if prior and prior.get("user_sub") == sub:
                    return prior
        _reservation_failed(sub, month, held_since, held_id)
        raise

    # The start of the search's Langfuse trace. Pipeline Lambdas join the same
    # trace by deriving its id from search_id. Only ids and parameters that
    # say nothing about the user are recorded — no sub, no coordinates, no
    # free text. Tracing failures never reach the request (observability.py).
    # Imported here, not at module top: fmaj_agent.config reads the environment
    # at import time, after app.settings has loaded api/.env.
    from fmaj_agent import config as agent_config
    from fmaj_agent import observability

    labels = [r.label for r in req.roles]
    with observability.observe(
        "api.create_search",
        search_id=search_id,
        trace_meta={"search_id": search_id, "role": ", ".join(labels)[:200],
                    "provider": agent_config.LLM_PROVIDER},
        tags=[f"stage:{settings.stage}", f"provider:{agent_config.LLM_PROVIDER}",
              *[f"role:{r}" for r in labels[:3]]],
        input={"roles": labels, "radius_km": req.radius_km},
    ) as obs:
        obs.update(output={"status": meta["status"], "pipeline_started": False})
        if not settings.state_machine_arn:
            obs.update(level="WARNING", status_message="workflow dispatcher is not configured")
    # The DynamoDB INSERT stream is the durable handoff. Its consumer starts the
    # workflow and records the execution ARN; returning pending is intentional.
    observability.flush(timeout=1.0)
    return meta


def _trace_id(search_id: str) -> str:
    from fmaj_agent.observability import trace_id_for

    return trace_id_for(search_id)


def list_searches(sub: str, limit: int = 10) -> list[dict]:
    """The user's most recent searches, newest first — the workspace left rail."""
    resp = _get_table().query(
        KeyConditionExpression=Key("PK").eq(f"USER#{sub}")
        & Key("SK").begins_with("SEARCH#"),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [
        {
            "search_id": i["search_id"],
            "roles": list(i.get("roles", [])),
            "location_label": i.get("location_label", ""),
            "lat": float(i["lat"]),
            "lng": float(i["lng"]),
            "radius_km": float(i["radius_km"]),
            "created_at": i["created_at"],
        }
        for i in resp.get("Items", [])
    ]


class NotStoppable(Exception):
    """The search isn't running any more, so there is nothing to stop."""


class StopFailed(Exception):
    """The workflow could not be stopped; status remains unchanged."""


def stop_search(sub: str, search_id: str) -> dict | None:
    """Halt a running search: stop the execution, then mark it `cancelled`.

    `cancelled` is deliberately its own status, not `failed`. The user chose to
    stop; showing them an error would be a lie, and whatever results already
    landed are still real and worth keeping on screen.
    """
    resp = _get_table().get_item(
        Key={"PK": f"SEARCH#{search_id}", "SK": "META"}
    )
    meta = resp.get("Item")
    if meta is None or meta.get("user_sub") != sub:
        return None
    if meta.get("status") not in ("pending", "running"):
        raise NotStoppable(meta.get("status", "unknown"))

    arn = meta.get("execution_arn")
    if arn:
        # Do not claim success if Step Functions could not stop the execution.
        # A concurrently finished execution is resolved by the conditional state
        # transition below, which reports its actual terminal state.
        try:
            _get_sfn().stop_execution(
                executionArn=arn, cause="Stopped by the user", error="UserStopped"
            )
        except ClientError as exc:
            raise StopFailed from exc

    try:
        _get_table().update_item(
            Key={"PK": f"SEARCH#{search_id}", "SK": "META"},
            UpdateExpression="SET #s = :s, cancelled_at = :t",
            ConditionExpression="#s IN (:pending, :running)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "cancelled",
                ":t": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 — Python 3.10 tooling compatibility
                ":pending": "pending",
                ":running": "running",
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            latest = _get_table().get_item(
                Key={"PK": f"SEARCH#{search_id}", "SK": "META"}
            ).get("Item") or {}
            raise NotStoppable(latest.get("status", "unknown")) from exc
        raise
    # Stopping is the user telling us they're done with this one; making them
    # wait out the lease before they can start another would be perverse.
    _release_search_lease(sub, search_id)
    return {"search_id": search_id, "status": "cancelled"}


def get_search(sub: str, search_id: str) -> dict | None:
    """Return META + results for the owner, or None if not found / not owner."""
    resp = _get_table().query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": f"SEARCH#{search_id}"},
    )
    items = resp.get("Items", [])
    meta = next((i for i in items if i["SK"] == "META"), None)
    if meta is None or meta.get("user_sub") != sub:
        return None
    results = [i for i in items if i["SK"].startswith("RESULT#")]

    # PIN# items carry the map coordinates for each result. They're a separate,
    # TTL'd item (Places data must not outlive the search), so they may be absent
    # for older searches or after they expire — a result without a pin just isn't
    # placed on the map.
    pins = {
        i["SK"].removeprefix("PIN#"): i
        for i in items
        if i["SK"].startswith("PIN#")
    }

    # Trace rows for the live "What I'm doing" panel. The SK embeds an ISO
    # timestamp, so sorting by it is chronological.
    steps = sorted(
        (i for i in items if i["SK"].startswith("STEP#")),
        key=lambda i: i["SK"],
    )

    # Progress: how many of the discovered companies the agent has finished.
    # company_count is written by discover_handler; until then we don't know the
    # denominator, so report 0 rather than guessing from partial results.
    total_companies = int(meta.get("company_count", 0) or 0)
    done = sum(1 for r in results if r.get("opportunity_type", "pending") != "pending")

    def _coords(place_id: str) -> tuple[float | None, float | None]:
        """Parse a result's stored pin coordinates, or (None, None) if absent."""
        pin = pins.get(place_id)
        if not pin:
            return None, None
        try:
            return float(pin["lat"]), float(pin["lng"])
        except (KeyError, TypeError, ValueError):
            return None, None

    def _result(r: dict) -> dict:
        place_id = r["SK"].removeprefix("RESULT#")
        lat, lng = _coords(place_id)
        return {
            "place_id": place_id,
            "company": r.get("company", ""),
            "address": r.get("address", ""),
            "opportunity_type": r.get("opportunity_type", "pending"),
            "links": list(r.get("links", [])),
            "emails": list(r.get("emails", [])),
            # The agent's one-line justification. Stored by the pipeline since
            # Phase 3; the results page now shows it.
            "evidence": r.get("evidence", ""),
            "website": r.get("website", ""),
            # Coordinates for the numbered map pin, when we still have them.
            "lat": lat,
            "lng": lng,
        }

    return {
        "search_id": search_id,
        "status": meta["status"],
        "company_errors": int(meta.get("company_errors", 0) or 0),
        "error_code": meta.get("error_code", ""),
        "retryable": bool(meta.get("retryable", False)),
        "progress": {"done": done, "total": total_companies},
        "steps": [
            {
                "tag": s.get("tag", "checking"),
                "tool": s.get("tool", ""),
                "text": s.get("text", ""),
                "meta": s.get("meta", ""),
                "at": s.get("at", ""),
            }
            for s in steps
        ],
        "params": {
            "lat": float(meta["lat"]),
            "lng": float(meta["lng"]),
            "radius_km": float(meta["radius_km"]),
            # roles are stored as dicts now, but older searches hold plain strings
            "roles": [r["label"] if isinstance(r, dict) else r
                      for r in meta.get("roles", [])],
            "query_text": meta.get("query_text", ""),
            "location_label": meta.get("location_label", ""),
        },
        "created_at": meta["created_at"],
        "results": [_result(r) for r in results],
        "total": len(results),
    }
