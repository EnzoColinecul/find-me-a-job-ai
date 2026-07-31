"""Shared data models for the per-company agent."""
from enum import Enum

from pydantic import BaseModel, Field


class OpportunityType(str, Enum):
    CAREERS_PAGE = "careers_page"
    JOB_LISTING = "job_listing"
    CONTACT_EMAIL = "contact_email"
    NONE = "none"


class Company(BaseModel):
    """Input: one company discovered via Google Places."""

    place_id: str
    name: str
    address: str
    types: list[str] = []
    website: str | None = None
    roles: list[str]


class Findings(BaseModel):
    """Output: strict schema the agent must report."""

    opportunity_type: OpportunityType
    links: list[str] = []
    emails: list[str] = []
    evidence: str = Field(default="", description="Short justification of the finding")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ToolResult(BaseModel):
    """Every tool returns this — tools never raise."""

    ok: bool
    data: dict = {}
    reason: str = ""
