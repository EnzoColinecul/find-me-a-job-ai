"""Search creation and retrieval.

Table items:
  SEARCH#<id> / META               — params, status, owner, counts
  SEARCH#<id> / RESULT#<place_id>  — written incrementally by the agent pipeline
Status: pending -> running -> completed | failed
"""
import json
import logging
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field, field_validator

from app.settings import settings

# rough Australia bounding box (PoC market restriction)
AU_LAT = (-44.0, -9.5)
AU_LNG = (112.0, 154.5)
MAX_ROLES = 3
MAX_RADIUS_KM = 10.0


class SearchRequest(BaseModel):
    lat: float
    lng: float
    radius_km: float = Field(gt=0, le=MAX_RADIUS_KM)
    roles: list[str] = Field(min_length=1, max_length=MAX_ROLES)

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
    def _clean_roles(cls, v: list[str]) -> list[str]:
        cleaned = [r.strip().lower() for r in v if r.strip()]
        if not cleaned:
            raise ValueError("At least one role required")
        return cleaned[:MAX_ROLES]


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
        "roles": req.roles,
        "status": "pending",
        "created_at": now,
    }
    _get_table().put_item(Item=meta)

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
                        "roles": req.roles,
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
            "roles": list(meta["roles"]),
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
            }
            for r in results
        ],
        "total": len(results),
    }
