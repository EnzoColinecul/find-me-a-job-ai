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
from datetime import datetime, timezone

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
    pass


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


def create_search(sub: str, req: SearchRequest) -> dict:
    """Consume quota, persist the search, kick the pipeline. Returns the META item."""
    _consume_free_search(sub)

    search_id = uuid.uuid4().hex[:12]
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
            _get_sfn().start_execution(
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
    return {
        "search_id": search_id,
        "status": meta["status"],
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
        "results": [
            {
                "place_id": r["SK"].removeprefix("RESULT#"),
                "company": r.get("company", ""),
                "address": r.get("address", ""),
                "opportunity_type": r.get("opportunity_type", "pending"),
                "links": list(r.get("links", [])),
                "emails": list(r.get("emails", [])),
                # The agent's one-line justification. Stored by the pipeline
                # since Phase 3; the results page now shows it.
                "evidence": r.get("evidence", ""),
                "website": r.get("website", ""),
            }
            for r in results
        ],
        "total": len(results),
    }
