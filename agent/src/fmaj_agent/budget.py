"""Metered-API spend shared across one search's parallel company Lambdas.

The problem this solves: companies are investigated in a Step Functions Map, so
each runs in its own Lambda with its own memory. A per-company cap is therefore
the only thing enforceable in process, and the true ceiling for a search is the
*product* of two knobs — `MAX_COMPANIES x MAX_WEB_SEARCHES`.

That product coupled two unrelated decisions. Protecting SerpAPI's ~250-a-month
free tier meant cutting `MAX_COMPANIES` to 5, which cut the number of places the
user is shown by the same factor, even though most companies never reach
`web_search` at all (the prompt tries their own site and Adzuna first).

A counter item in DynamoDB is the shared memory those Lambdas lack. With a real
per-search ceiling, breadth stops paying for depth: `MAX_COMPANIES` can go back
up without multiplying the SerpAPI bill.

The per-company cap stays. It is the backstop for the case below where this
counter can't be reached, and two cheap guards are worth more than one clever
one.
"""
import logging
import time
from typing import Protocol

import boto3
from botocore.exceptions import ClientError

from fmaj_agent import config
from fmaj_agent.config import AWS_REGION

logger = logging.getLogger(__name__)

TABLE_NAME = f"fmaj-{config.STAGE}-main"

#: Same 7 days as the trace steps: a spend counter is progress, not a record.
BUDGET_TTL_SECONDS = 7 * 24 * 3600


class SearchBudget(Protocol):
    """Reserve one call of a metered tool; return a refusal reason or None."""

    def reserve(self, tool: str) -> str | None: ...


class NoSharedBudget:
    """No shared ceiling — local runs, the one-company runner, and tests.

    Not a degraded mode: outside the pipeline there is only ever one company in
    flight, so the per-company cap already is the per-search cap.
    """

    def reserve(self, tool: str) -> str | None:  # noqa: ARG002
        return None


class DynamoSearchBudget:
    """One counter item per search, shared by every company Lambda under it.

    `SEARCH#<id> / BUDGET`, one attribute per metered tool, incremented with a
    conditional ADD so the check and the increment are a single operation —
    reading the count and then writing it would let two parallel Lambdas both
    see 9 and both proceed.
    """

    def __init__(self, search_id: str, table=None) -> None:
        self.search_id = search_id
        self._table = table

    def _get_table(self):
        if self._table is None:
            self._table = boto3.resource(
                "dynamodb", region_name=AWS_REGION
            ).Table(TABLE_NAME)
        return self._table

    def reserve(self, tool: str) -> str | None:
        cap = config.shared_cap(tool)
        if not cap:  # unset or 0 == unlimited
            return None
        try:
            self._get_table().update_item(
                Key={"PK": f"SEARCH#{self.search_id}", "SK": "BUDGET"},
                UpdateExpression="ADD #t :one SET expires_at = :ttl",
                ConditionExpression="attribute_not_exists(#t) OR #t < :cap",
                ExpressionAttributeNames={"#t": tool},
                ExpressionAttributeValues={
                    ":one": 1,
                    ":cap": cap,
                    ":ttl": int(time.time()) + BUDGET_TTL_SECONDS,
                },
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return f"budget reached: {cap} {tool} call(s) for this search"
            # Fail OPEN. A DynamoDB error here is not a reason to hand the user a
            # worse search, and the per-company cap still bounds the damage at
            # the old arithmetic worst case — which is exactly what we ran on
            # before this counter existed.
            logger.warning(
                "shared budget unavailable for %s (%s) — falling back to the "
                "per-company cap", self.search_id, exc,
            )
            return None
        return None
