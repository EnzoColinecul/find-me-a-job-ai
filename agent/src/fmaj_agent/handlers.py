"""Lambda handlers for the search pipeline (Step Functions).

State machine (PipelineStack):
  Discover -> Map(InvestigateCompany, maxConcurrency N) -> Aggregate

Each handler writes to DynamoDB incrementally so the frontend's polling endpoint
(GET /searches/{id}) can stream progress. Handlers are also runnable locally.
"""
import logging
import os
from datetime import datetime, timezone

import boto3

from fmaj_agent.discovery import discover
from fmaj_agent.models import Company
from fmaj_agent.orchestrator import investigate

logger = logging.getLogger(__name__)
logging.getLogger().setLevel(logging.INFO)

TABLE_NAME = os.environ.get("FMAJ_TABLE_NAME", "fmaj-test-main")
AWS_REGION = os.environ.get("FMAJ_AWS_REGION", "ap-southeast-2")

_table = None


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_NAME)
    return _table


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def discover_handler(event: dict, _context=None) -> dict:
    """Input: {search_id, lat, lng, radius_km, roles}. Writes queued RESULT# items.

    Output: {search_id, companies: [company dicts]} consumed by the Map state.
    """
    search_id = event["search_id"]
    table = _get_table()
    table.update_item(
        Key={"PK": f"SEARCH#{search_id}", "SK": "META"},
        UpdateExpression="SET #s = :s, discovery_started_at = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "running", ":t": _now()},
    )

    result = discover(
        lat=float(event["lat"]),
        lng=float(event["lng"]),
        radius_km=float(event["radius_km"]),
        roles=list(event["roles"]),  # RoleSpec dicts (or legacy plain strings)
    )
    for company in result.companies:
        table.put_item(Item={
            "PK": f"SEARCH#{search_id}",
            "SK": f"RESULT#{company.place_id}",
            "company": company.name,
            "address": company.address,
            "website": company.website or "",
            "opportunity_type": "pending",
            "links": [],
            "emails": [],
        })
    table.update_item(
        Key={"PK": f"SEARCH#{search_id}", "SK": "META"},
        UpdateExpression="SET company_count = :c, discovery_stats = :st",
        ExpressionAttributeValues={":c": len(result.companies),
                                   ":st": {k: str(v) for k, v in result.stats.items()}},
    )
    logger.info("search %s: discovered %d companies %s",
                search_id, len(result.companies), result.stats)
    return {
        "search_id": search_id,
        "companies": [c.model_dump() for c in result.companies],
    }


def investigate_handler(event: dict, _context=None) -> dict:
    """Input (one Map item): {search_id, company: {...}}. Writes the RESULT# item."""
    search_id = event["search_id"]
    company = Company(**event["company"])
    run = investigate(company)  # never raises
    f = run.findings
    _get_table().update_item(
        Key={"PK": f"SEARCH#{search_id}", "SK": f"RESULT#{company.place_id}"},
        UpdateExpression=("SET opportunity_type = :o, links = :l, emails = :e, "
                          "evidence = :v, confidence = :c, agent_stats = :st, "
                          "investigated_at = :t"),
        ExpressionAttributeValues={
            ":o": f.opportunity_type.value,
            ":l": f.links,
            ":e": f.emails,
            ":v": f.evidence,
            ":c": str(f.confidence),
            ":st": {k: str(v) for k, v in run.stats().items()},
            ":t": _now(),
        },
    )
    logger.info("search %s / %s -> %s (tools=%d tokens=%d/%d)",
                search_id, company.name, f.opportunity_type.value,
                run.tool_calls, run.input_tokens, run.output_tokens)
    return {"place_id": company.place_id, "opportunity_type": f.opportunity_type.value}


def aggregate_handler(event: dict, _context=None) -> dict:
    """Input: {search_id, results: [investigate outputs]}. Finalizes the search."""
    search_id = event["search_id"]
    results = event.get("results", [])
    counts: dict[str, int] = {}
    for r in results:
        counts[r["opportunity_type"]] = counts.get(r["opportunity_type"], 0) + 1
    _get_table().update_item(
        Key={"PK": f"SEARCH#{search_id}", "SK": "META"},
        UpdateExpression="SET #s = :s, completed_at = :t, opportunity_counts = :c",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "completed", ":t": _now(), ":c": counts},
    )
    logger.info("search %s completed: %s", search_id, counts)
    return {"search_id": search_id, "counts": counts}


def fail_handler(event: dict, _context=None) -> dict:
    """Catch-all: mark the search failed (wired to state machine error catch)."""
    search_id = event.get("search_id") or (event.get("input") or {}).get("search_id", "")
    if search_id:
        _get_table().update_item(
            Key={"PK": f"SEARCH#{search_id}", "SK": "META"},
            UpdateExpression="SET #s = :s, failed_at = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "failed", ":t": _now()},
        )
    logger.error("search %s failed: %s", search_id, event.get("error"))
    return {"search_id": search_id, "status": "failed"}
