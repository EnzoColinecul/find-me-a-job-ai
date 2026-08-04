"""Lambda handlers for the search pipeline (Step Functions).

State machine (PipelineStack):
  Discover -> Map(InvestigateCompany, maxConcurrency N) -> Aggregate

Each handler writes to DynamoDB incrementally so the frontend's polling endpoint
(GET /searches/{id}) can stream progress. Handlers are also runnable locally.
"""
import logging
import os
import time
from datetime import datetime, timezone

import boto3

from fmaj_agent import config
from fmaj_agent.discovery import discover
from fmaj_agent.models import Company
from fmaj_agent.orchestrator import investigate
from fmaj_agent.trace import Tag, TraceStep

logger = logging.getLogger(__name__)
logging.getLogger().setLevel(logging.INFO)

TABLE_NAME = os.environ.get("FMAJ_TABLE_NAME", "fmaj-test-main")
AWS_REGION = os.environ.get("FMAJ_AWS_REGION", "ap-southeast-2")

#: Trace rows are live progress, not a record of the search. 7 days is long
#: enough to debug a run and short enough that we're not sitting on Places data.
#: Requires TTL enabled on `expires_at` for the table (see infra/data_stack).
STEP_TTL_SECONDS = 7 * 24 * 3600

_table = None


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_NAME)
    return _table


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _put_step(search_id: str, step: TraceStep) -> None:
    """Persist one trace row so the UI can show it while the search is running.

    Sort key is the ISO timestamp, which sorts chronologically as a string; the
    place_id suffix keeps two companies that emit in the same microsecond from
    colliding. Companies are investigated in parallel, so a per-run sequence
    number would not give a meaningful global order.

    Steps carry a TTL: they are progress, not a record. Keeping them forever
    would also mean holding Places-derived company names indefinitely, which the
    Places terms don't allow.
    """
    _get_table().put_item(Item={
        "PK": f"SEARCH#{search_id}",
        "SK": f"STEP#{step.at}#{step.place_id or 'x'}",
        **step.to_item(),
        "expires_at": int(time.time()) + STEP_TTL_SECONDS,
    })


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
    logger.info("search %s budgets: %s", search_id, config.budget_summary())
    n = len(result.companies)
    # roles arrive as RoleSpec dicts, or plain strings on older searches
    labels = [r["label"] if isinstance(r, dict) else str(r) for r in event["roles"]]
    _put_step(search_id, TraceStep(
        tag=Tag.SEARCHING, tool="discovery",
        text=", ".join(labels[:2]) or "nearby businesses",
        meta=f"{n} place{'s' if n != 1 else ''} found",
    ))
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
    # Steps are written as they happen, so the panel fills in while the Map
    # state is still running rather than all at once at the end.
    run = investigate(company, on_step=lambda s: _put_step(search_id, s))
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
    logger.info("search %s / %s -> %s (tools=%d web_search=%d tokens=%d/%d)",
                search_id, company.name, f.opportunity_type.value,
                run.tool_calls, run.metered_calls.get("web_search", 0),
                run.input_tokens, run.output_tokens)
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
