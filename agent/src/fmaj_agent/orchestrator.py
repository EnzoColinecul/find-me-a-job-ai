"""Bedrock Converse tool-use loop — the per-company agent.

Design (see docs/PLAN.md §4):
- Haiku 4.5 triage: "is this company plausible for role X?" before spending Sonnet tokens.
- Sonnet 4.5 (au. cross-region profile) drives the tool loop.
- HARD BUDGETS IN CODE, not prompt: max 8 tool calls, ~60s wall time, token cap.
  On breach -> finalize with whatever was found.
- Output enforced via a `report_findings` tool the model must call (models.Findings).
- Log every LLM call: model, tokens in/out, estimated cost.
"""
from fmaj_agent.models import Company, Findings, OpportunityType

MAX_TOOL_CALLS = 8
MAX_SECONDS = 60

MODEL_ORCHESTRATOR = "au.anthropic.claude-sonnet-4-5"  # verify exact profile id at deploy
MODEL_TRIAGE = "au.anthropic.claude-haiku-4-5"


def investigate(company: Company) -> Findings:
    """Run the full investigation for one company. Never raises."""
    # TODO(Phase 3): triage -> tool loop -> report_findings
    return Findings(opportunity_type=OpportunityType.NONE, evidence="not implemented")
