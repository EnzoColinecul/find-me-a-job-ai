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
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field, field_validator, model_validator

from app.settings import settings

# rough Australia bounding box (PoC market restriction)
AU_LAT = (-44.0, -9.5)
AU_LNG = (112.0, 154.5)


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
    def _lat_in_au(cls, v: float) -> float:
        if not AU_LAT[0] <= v <= AU_LAT[1]:
            raise ValueError("Location must be within Australia")
        return v

    @field_validator("lng")
    @classmethod
    def _lng_in_au(cls, v: float) -> float:
        if not AU_LNG[0] <= v <= AU_LNG[1]:
            raise ValueError("Location must be within Australia")
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


def _consume_free_search(sub: str) -> None:
    """Flip free_search_used False->True atomically; raise QuotaExhausted otherwise."""
    try:
        _get_table().update_item(
            Key={"PK": f"USER#{sub}", "SK": "PROFILE"},
            UpdateExpression="SET free_search_used = :t",
            ConditionExpression="attribute_exists(PK) AND free_search_used = :f",
            ExpressionAttributeValues={":t": True, ":f": False},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise QuotaExhausted from exc
        raise


def _month_key(when: datetime | None = None) -> str:
    return (when or datetime.now(timezone.utc)).strftime("%Y-%m")


def _reserve_monthly_slot() -> str | None:
    """Take one of this month's searches, or raise MonthlyCapReached.

    A single counter item incremented conditionally, so the check and the
    increment are one operation — reading the count and then writing it would
    let two concurrent requests both see 29 and both proceed.

    Returns the month key so the caller can hand the slot back if a later step
    fails. None when the cap is switched off.
    """
    cap = settings.global_monthly_searches
    if cap <= 0:
        return None
    month = _month_key()
    try:
        _get_table().update_item(
            Key={"PK": "SYSTEM#QUOTA", "SK": f"MONTH#{month}"},
            UpdateExpression="ADD #c :one",
            ConditionExpression="attribute_not_exists(#c) OR #c < :cap",
            ExpressionAttributeNames={"#c": "count"},
            ExpressionAttributeValues={":one": 1, ":cap": cap},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise MonthlyCapReached from exc
        raise
    return month


def _release_monthly_slot(month: str | None) -> None:
    """Hand a reserved slot back after a later step failed."""
    if month is None:
        return
    try:
        _get_table().update_item(
            Key={"PK": "SYSTEM#QUOTA", "SK": f"MONTH#{month}"},
            UpdateExpression="ADD #c :minus",
            ConditionExpression="#c > :zero",
            ExpressionAttributeNames={"#c": "count"},
            ExpressionAttributeValues={":minus": -1, ":zero": 0},
        )
    except ClientError as exc:
        # Losing a slot is a rounding error against the month's budget; failing
        # the user's request to report it would not be.
        logger.warning("could not release monthly slot for %s: %s", month, exc)


TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _search_is_finished(search_id: str) -> bool:
    """True if the named search is over — or gone, which amounts to the same."""
    if not search_id:
        return True
    item = _get_table().get_item(
        Key={"PK": f"SEARCH#{search_id}", "SK": "META"}
    ).get("Item")
    if item is None:
        return True
    return item.get("status") in TERMINAL_STATUSES


def _acquire_search_lease(sub: str, search_id: str) -> None:
    """Claim this user's one concurrent search slot, or raise SearchInProgress.

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
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(minutes=settings.search_lease_minutes)).isoformat()

    profile = _get_table().get_item(
        Key={"PK": f"USER#{sub}", "SK": "PROFILE"}
    ).get("Item") or {}
    held_since = profile.get("active_since") or ""
    held_id = profile.get("active_search_id") or ""

    # ISO-8601 UTC strings sort lexicographically, so this is a real comparison.
    if held_since >= cutoff and not _search_is_finished(held_id):
        raise SearchInProgress

    try:
        _get_table().update_item(
            Key={"PK": f"USER#{sub}", "SK": "PROFILE"},
            UpdateExpression="SET active_since = :now, active_search_id = :sid",
            # Compare-and-swap against what we just read. Two requests that both
            # decide the old lease is dead can't both take it — the second one's
            # condition no longer matches and it gets SearchInProgress, which is
            # the truth by then.
            ConditionExpression=(
                "attribute_exists(PK) AND ("
                "attribute_not_exists(active_since) OR active_since = :expected)"
            ),
            ExpressionAttributeValues={
                ":now": now.isoformat(),
                ":sid": search_id,
                ":expected": held_since,
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise SearchInProgress from exc
        raise


def _release_search_lease(sub: str) -> None:
    """Free the concurrency slot early, rather than waiting for the lease out."""
    try:
        _get_table().update_item(
            Key={"PK": f"USER#{sub}", "SK": "PROFILE"},
            UpdateExpression="SET active_since = :none, active_search_id = :none",
            ExpressionAttributeValues={":none": ""},
        )
    except ClientError as exc:
        logger.warning("could not release search lease for %s: %s", sub, exc)


def create_search(sub: str, req: SearchRequest) -> dict:
    """Consume quota, persist the search, kick the pipeline. Returns the META item.

    Three gates, cheapest and most-reversible first, so a rejection never eats
    something the user can't get back:
      1. concurrency lease — catches the double-clicked button
      2. this month's global cap — protects the free tiers
      3. this user's free search — the only irreversible one
    """
    search_id = uuid.uuid4().hex[:12]

    _acquire_search_lease(sub, search_id)
    try:
        month = _reserve_monthly_slot()
    except Exception:
        _release_search_lease(sub)
        raise
    try:
        _consume_free_search(sub)
    except Exception:
        _release_monthly_slot(month)
        _release_search_lease(sub)
        raise

    now = datetime.now(timezone.utc).isoformat()
    meta = {
        "PK": f"SEARCH#{search_id}",
        "SK": "META",
        "search_id": search_id,
        "user_sub": sub,
        "lat": str(req.lat),
        "lng": str(req.lng),
        "radius_km": str(req.radius_km),
        "roles": [r.model_dump() for r in req.roles],
        "query_text": req.query_text or "",
        "location_label": req.location_label or "",
        "status": "pending",
        "created_at": now,
    }
    _get_table().put_item(Item=meta)

    # Owner index. Sorting by created_at inside the SK means "most recent first"
    # is just a reverse query — no filtering, no scan.
    _get_table().put_item(
        Item={
            "PK": f"USER#{sub}",
            "SK": f"SEARCH#{now}#{search_id}",
            "search_id": search_id,
            "roles": [r.label for r in req.roles],
            "location_label": req.location_label or "",
            "lat": str(req.lat),
            "lng": str(req.lng),
            "radius_km": str(req.radius_km),
            "created_at": now,
        }
    )

    if settings.state_machine_arn:
        try:
            execution = _get_sfn().start_execution(
                stateMachineArn=settings.state_machine_arn,
                name=f"search-{search_id}",
                input=json.dumps(
                    {
                        "search_id": search_id,
                        "lat": req.lat,
                        "lng": req.lng,
                        "radius_km": req.radius_km,
                        "roles": [r.model_dump() for r in req.roles],
                    }
                ),
            )
            # Stored rather than reconstructed from the state machine ARN: the
            # execution name is ours today, but deriving an ARN by string
            # surgery would break silently if that ever changed.
            _get_table().update_item(
                Key={"PK": f"SEARCH#{search_id}", "SK": "META"},
                UpdateExpression="SET execution_arn = :a",
                ExpressionAttributeValues={":a": execution["executionArn"]},
            )
        except ClientError as exc:
            # Pipeline not deployed / bad ARN: don't fail the request. The search
            # record exists and stays "pending" — visible in the UI and logs.
            logger.error("failed to start pipeline for %s: %s", search_id, exc)
    else:
        logger.warning("FMAJ_STATE_MACHINE_ARN not set — search %s stays pending",
                       search_id)
    return meta


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
        try:
            _get_sfn().stop_execution(
                executionArn=arn, cause="Stopped by the user", error="UserStopped"
            )
        except ClientError as exc:
            # Already finished, or the pipeline isn't deployed. The user asked
            # for it to stop; record that rather than leaving it "running"
            # forever, but don't claim we halted something we didn't.
            logger.warning("stop_execution failed for %s: %s", search_id, exc)

    _get_table().update_item(
        Key={"PK": f"SEARCH#{search_id}", "SK": "META"},
        UpdateExpression="SET #s = :s, cancelled_at = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "cancelled",
            ":t": datetime.now(timezone.utc).isoformat(),
        },
    )
    # Stopping is the user telling us they're done with this one; making them
    # wait out the lease before they can start another would be perverse.
    _release_search_lease(sub)
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
