"""Lambda handlers for the search pipeline (Step Functions).

State machine (PipelineStack):
  Discover -> Map(InvestigateCompany, maxConcurrency N) -> Aggregate

Each handler writes to DynamoDB incrementally so the frontend's polling endpoint
(GET /searches/{id}) can stream progress. Handlers are also runnable locally.
"""
import json
import logging
import os
import random
import time
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from fmaj_agent import config, observability
from fmaj_agent.budget import DynamoSearchBudget
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

#: Map-pin coordinates are the one piece of Places data we now persist beyond the
#: search, so they live on their own PIN# item with a TTL rather than on the
#: durable RESULT# row. CLAUDE.md: "don't persist place data beyond the search
#: (place_id is exempt)" — keying by the exempt place_id and expiring the lat/lng
#: keeps the coordinates from outliving the search, while the result cards (which
#: the user came back for) are left untouched. 7 days matches the trace rows.
PIN_TTL_SECONDS = 7 * 24 * 3600

_table = None
_serializer = TypeSerializer()


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_NAME)
    return _table


def _search_status(search_id: str) -> str:
    item = _get_table().get_item(Key={"PK": f"SEARCH#{search_id}", "SK": "META"}).get("Item") or {}
    return str(item.get("status", "unknown"))


def _search_cancelled(search_id: str) -> bool:
    return _search_status(search_id) == "cancelled"


def _search_stopped(search_id: str) -> bool:
    return _search_status(search_id) not in {"pending", "running"}


def _av(values: dict) -> dict:
    return {key: _serializer.serialize(value) for key, value in values.items()}


def _write_while_running(search_id: str, actions: list[dict]) -> None:
    """Commit row changes only while META is running, atomically with cancel.

    Step Functions cannot stop a Lambda already in flight. Conditioning these
    writes on the META row makes stop and a result commit a serialized choice:
    whichever transaction wins happens first, and no later result can mutate a
    cancelled/terminal search.
    """
    table = _get_table()
    check = {"ConditionCheck": {
        "TableName": table.name,
        "Key": _av({"PK": f"SEARCH#{search_id}", "SK": "META"}),
        "ConditionExpression": "#s = :running",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": _av({":running": "running"}),
    }}
    request = {
        "TransactItems": [check, *actions],
        "ClientRequestToken": uuid.uuid4().hex,
    }
    for attempt in range(3):
        try:
            table.meta.client.transact_write_items(**request)
            return
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            transient = code in {
                "TransactionConflictException",
                "ProvisionedThroughputExceededException",
                "ThrottlingException",
            }
            if not transient or attempt == 2:
                raise
            time.sleep(0.05 * (2**attempt) + random.random() * 0.05)


def _put_while_running(search_id: str, item: dict) -> None:
    table = _get_table()
    action = {"Put": {"TableName": table.name, "Item": _av(item)}}
    _write_while_running(search_id, [action])


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

    **This never raises.** The trace is a view onto the work, not the work — a
    throttled write or a missing table must not be able to fail a real search.
    The orchestrator's sink is already wrapped, but `discover_handler` calls this
    directly, so the guarantee belongs here too.
    """
    try:
        _put_while_running(search_id, {
            "PK": f"SEARCH#{search_id}",
            "SK": f"STEP#{step.at}#{step.place_id or 'x'}",
            **step.to_item(),
            "expires_at": int(time.time()) + STEP_TTL_SECONDS,
        })
    except Exception:  # noqa: BLE001
        logger.warning("could not record trace step %s for %s",
                       step.tool, search_id, exc_info=True)


def _role_labels(roles: list) -> list[str]:
    # roles arrive as RoleSpec dicts, or plain strings on older searches
    return [r["label"] if isinstance(r, dict) else str(r) for r in roles]


def _search_trace(search_id: str, roles: list, **meta) -> dict:
    """Trace-level metadata/tags shared by every pipeline step of a search."""
    labels = _role_labels(roles)
    return {
        "search_id": search_id,
        "trace_meta": {"search_id": search_id, "role": ", ".join(labels)[:200],
                       "provider": config.LLM_PROVIDER, **meta},
        "tags": [f"stage:{config.STAGE}", f"provider:{config.LLM_PROVIDER}",
                 *[f"role:{r}" for r in labels[:3]]],
    }


def discover_handler(event: dict, _context=None) -> dict:
    """Input: {search_id, lat, lng, radius_km, roles}. Writes queued RESULT# items.

    Output: {search_id, companies: [company dicts]} consumed by the Map state.
    """
    if _search_stopped(event["search_id"]):
        return {"search_id": event["search_id"], "companies": []}
    try:
        with observability.observe(
            "discovery", metadata={"radius_km": event.get("radius_km")},
            **_search_trace(event["search_id"], list(event.get("roles") or [])),
        ) as obs:
            try:
                out = _discover(event)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"TransactionCanceledException", "ConditionalCheckFailedException"} \
                        and _search_stopped(event["search_id"]):
                    return {"search_id": event["search_id"], "companies": []}
                raise
            if _search_stopped(event["search_id"]):
                return {"search_id": event["search_id"], "companies": []}
            companies = out["companies"]
            countries: dict[str, int] = {}
            for c in companies:
                code = c.get("country_code") or "unknown"
                countries[code] = countries.get(code, 0) + 1
            obs.update(output={"companies": len(companies), "countries": countries})
            return out
    finally:
        observability.flush()


def _discover(event: dict) -> dict:
    search_id = event["search_id"]
    table = _get_table()
    table.update_item(
        Key={"PK": f"SEARCH#{search_id}", "SK": "META"},
        UpdateExpression="SET #s = :s, discovery_started_at = :t",
        ConditionExpression="#s IN (:pending, :running)",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "running", ":t": _now(),
                                   ":pending": "pending", ":running": "running"},
    )

    result = discover(
        lat=float(event["lat"]),
        lng=float(event["lng"]),
        radius_km=float(event["radius_km"]),
        roles=list(event["roles"]),  # RoleSpec dicts (or legacy plain strings)
    )
    for company in result.companies:
        company_item = {
            "PK": f"SEARCH#{search_id}",
            "SK": f"RESULT#{company.place_id}",
            "company": company.name,
            "address": company.address,
            "website": company.website or "",
            "opportunity_type": "pending",
            "links": [],
            "emails": [],
        }
        actions = [{"Put": {"TableName": table.name, "Item": _av(company_item)}}]
        # Coordinates go on a separate, expiring PIN# item — see PIN_TTL_SECONDS.
        # Stored as strings to match the META lat/lng and avoid DynamoDB's
        # float/Decimal handling; get_search parses them back. A company with no
        # coordinates simply gets no pin.
        if company.lat is not None and company.lng is not None:
            pin_item = {
                "PK": f"SEARCH#{search_id}",
                "SK": f"PIN#{company.place_id}",
                "lat": str(company.lat),
                "lng": str(company.lng),
                "expires_at": int(time.time()) + PIN_TTL_SECONDS,
            }
            actions.append({"Put": {"TableName": table.name, "Item": _av(pin_item)}})
        _write_while_running(search_id, actions)
    table.update_item(
        Key={"PK": f"SEARCH#{search_id}", "SK": "META"},
        UpdateExpression="SET company_count = :c, discovery_stats = :st",
        ConditionExpression="#s = :running",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":c": len(result.companies),
                                   ":st": {k: str(v) for k, v in result.stats.items()},
                                   ":running": "running"},
    )
    logger.info("search %s budgets: %s", search_id, config.budget_summary())
    n = len(result.companies)
    labels = _role_labels(event["roles"])
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
    if _search_stopped(search_id):
        outcome = "cancelled" if _search_cancelled(search_id) else "terminal"
        return {"place_id": company.place_id, "opportunity_type": "pending",
                "outcome": outcome, "error_code": ""}
    # Steps are written as they happen, so the panel fills in while the Map
    # state is still running rather than all at once at the end.
    #
    # The budget is what lets MAX_COMPANIES be a product decision again: every
    # Lambda under this search spends against one counter, so raising the number
    # of companies no longer multiplies the SerpAPI bill.
    try:
        run = investigate(
            company,
            on_step=lambda s: None if _search_stopped(search_id) else _put_step(search_id, s),
            budget=DynamoSearchBudget(search_id, table=_get_table()),
            search_id=search_id,
            should_stop=lambda: _search_stopped(search_id),
        )
    finally:
        # The Lambda freezes on return; hand the spans over first (bounded).
        observability.flush()
    f = run.findings
    if run.cancelled or _search_stopped(search_id):
        outcome = "cancelled" if _search_cancelled(search_id) else "terminal"
        return {"place_id": company.place_id, "opportunity_type": "pending",
                "outcome": outcome, "error_code": ""}
    table = _get_table()
    result_update = {"Update": {
        "TableName": table.name,
        "Key": _av({"PK": f"SEARCH#{search_id}", "SK": f"RESULT#{company.place_id}"}),
        "UpdateExpression": ("SET opportunity_type = :o, links = :l, emails = :e, "
                             "evidence = :v, confidence = :c, agent_stats = :st, "
                             "investigated_at = :t"),
        "ExpressionAttributeValues": _av({
            ":o": f.opportunity_type.value,
            ":l": f.links,
            ":e": f.emails,
            ":v": f.evidence,
            ":c": str(f.confidence),
            ":st": {k: str(v) for k, v in run.stats().items()},
            ":t": _now(),
        }),
    }}
    try:
        _write_while_running(search_id, [result_update])
    except ClientError as exc:
        if (exc.response.get("Error", {}).get("Code") == "TransactionCanceledException"
                and _search_stopped(search_id)):
            outcome = "cancelled" if _search_cancelled(search_id) else "terminal"
            return {"place_id": company.place_id, "opportunity_type": "pending",
                    "outcome": outcome, "error_code": ""}
        raise
    logger.info("search %s / %s -> %s (tools=%d web_search=%d tokens=%d/%d)",
                search_id, company.name, f.opportunity_type.value,
                run.tool_calls, run.metered_calls.get("web_search", 0),
                run.input_tokens, run.output_tokens)
    return {"place_id": company.place_id, "opportunity_type": f.opportunity_type.value,
            "outcome": "error" if run.error else "success",
            "error_code": run.error.split(":", 1)[0] if run.error else ""}


def aggregate_handler(event: dict, _context=None) -> dict:
    """Input: {search_id, results: [investigate outputs]}. Finalizes the search."""
    search_id = event["search_id"]
    results = event.get("results", [])
    if _search_stopped(search_id):
        return {"search_id": search_id, "status": _search_status(search_id), "counts": {}}
    counts: dict[str, int] = {}
    for r in results:
        counts[r["opportunity_type"]] = counts.get(r["opportunity_type"], 0) + 1
    try:
        with observability.observe("aggregate", **_search_trace(search_id, [])) as obs:
            obs.update(output={"status": "completed", "companies": len(results),
                               "counts": counts})
    finally:
        observability.flush()
    failures = [r for r in results if r.get("outcome") == "error"]
    final_status = "failed" if failures and len(failures) == len(results) else (
        "degraded" if failures else "completed"
    )
    _get_table().update_item(
        Key={"PK": f"SEARCH#{search_id}", "SK": "META"},
        UpdateExpression="SET #s = :s, completed_at = :t, opportunity_counts = :c, "
                         "company_errors = :e",
        ConditionExpression="#s IN (:pending, :running)",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": final_status, ":t": _now(), ":c": counts,
                                   ":e": len(failures), ":pending": "pending", ":running": "running"},
    )
    logger.info("search %s %s: %s (%d company errors)", search_id, final_status,
                counts, len(failures))
    return {"search_id": search_id, "counts": counts, "status": final_status,
            "company_errors": len(failures)}


def fail_handler(event: dict, _context=None) -> dict:
    """Catch-all: mark the search failed (wired to state machine error catch)."""
    search_id = event.get("search_id") or (event.get("input") or {}).get("search_id", "")
    if not search_id:
        detail = event.get("detail") or {}
        execution_input = detail.get("input")
        if isinstance(execution_input, str):
            try:
                execution_input = json.loads(execution_input)
            except ValueError:
                execution_input = {}
        if isinstance(execution_input, dict):
            search_id = execution_input.get("search_id", "")
    detail = event.get("detail") or {}
    raw_error = event.get("error") or {}
    raw_name = str(raw_error.get("Error", "")) if isinstance(raw_error, dict) else ""
    execution_status = str(detail.get("status", "")).upper()
    if execution_status == "TIMED_OUT" or raw_name == "States.Timeout":
        error_code, retryable = "workflow_timeout", True
    elif execution_status == "ABORTED":
        error_code, retryable = "workflow_aborted", False
    elif raw_name in {"Lambda.ServiceException", "Lambda.SdkClientException"}:
        error_code, retryable = "lambda_service_error", True
    elif raw_name in {"States.Permissions", "AccessDeniedException"}:
        error_code, retryable = "permission_denied", False
    else:
        error_code, retryable = "workflow_failed", False
    if search_id:
        try:
            _get_table().update_item(
                Key={"PK": f"SEARCH#{search_id}", "SK": "META"},
                UpdateExpression="SET #s = :s, failed_at = :t, error_code = :ec, retryable = :r",
                ConditionExpression="#s IN (:pending, :running)",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "failed", ":t": _now(),
                                           ":pending": "pending", ":running": "running",
                                           ":ec": error_code, ":r": retryable},
            )
        except Exception as exc:
            if getattr(exc, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
    logger.error("search %s failed: %s", search_id, event.get("error"))
    if search_id:
        # Never persist Step Functions' Cause: it can contain request data or a
        # stack trace. Store only the bounded safe code above.
        try:
            with observability.observe("search.failed", **_search_trace(search_id, [])) as obs:
                obs.update(level="ERROR", status_message=error_code,
                           output={"status": "failed", "error_code": error_code,
                                   "retryable": retryable})
        finally:
            observability.flush()
    return {"search_id": search_id, "status": "failed", "error_code": error_code,
            "retryable": retryable}
