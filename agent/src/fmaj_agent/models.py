"""Shared data models for the per-company agent."""

from enum import Enum

from pydantic import BaseModel, Field


class OpportunityType(str, Enum):
    CAREERS_PAGE = "careers_page"
    JOB_LISTING = "job_listing"
    CONTACT_EMAIL = "contact_email"
    NONE = "none"


class RoleSuggestion(BaseModel):
    """A role proposed by the LLM from the user's free-text description."""

    label: str  # what the user sees / what the agent searches for
    curated_key: str | None = None  # role in role_mapping.yaml to borrow venue types from
    why: str = ""


class RoleSpec(BaseModel):
    """A confirmed role to search for."""

    label: str
    curated_key: str | None = None

    @property
    def mapping_key(self) -> str:
        """Which entry drives the Places types."""
        return self.curated_key or self.label


class Company(BaseModel):
    """Input: one company discovered via Google Places."""

    place_id: str
    name: str
    address: str
    types: list[str] = []
    website: str | None = None
    roles: list[str]
    # Read from the Places response so the results map can drop a numbered pin.
    # Optional: legacy discovery payloads (and any non-Places source) have none,
    # and a missing pin just means that card has no marker.
    lat: float | None = None
    lng: float | None = None
    # ISO-3166 alpha-2, lowercased ("au", "gb", "us"), from the Places address
    # components. Decides which job board the agent may reach for — Adzuna indexes
    # ~19 countries and Seek covers Australia only. None means "couldn't tell",
    # which the tools treat as "skip the country-specific boards", NOT as Australia.
    country_code: str | None = None
    #: Which discovery call first surfaced this place — a Places type
    #: ("nearby:cafe") or a text query ("text:software development company").
    #: Diagnostic only, never persisted: without it a harness CSV can't say
    #: whether a shortlist came from the types or the phrasings, which is
    #: exactly the question when a role is returning the wrong companies.
    discovery_source: str = ""


class Findings(BaseModel):
    """Output: strict schema the agent must report."""

    opportunity_type: OpportunityType
    links: list[str] = []
    emails: list[str] = []
    evidence: str = Field(default="", description="Short justification of the finding")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    #: For `job_listing` only: the exact vacancy title the agent matched against
    #: the role, copied from a tool result. It is what makes the claim checkable
    #: — `orchestrator._verify_listing` re-judges it and downgrades the finding if
    #: it isn't the role (or if no tool ever returned it). Not persisted; the
    #: user-facing justification lives in `evidence`.
    matched_title: str = Field(default="", description="Vacancy title matched to the role")


class ToolResult(BaseModel):
    """Every tool returns this — tools never raise."""

    ok: bool
    data: dict = {}
    reason: str = ""
