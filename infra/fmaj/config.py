"""Per-stage configuration. Everything stage-specific lives here."""
from dataclasses import dataclass


@dataclass(frozen=True)
class StageConfig:
    stage: str                     # "test" | "prod"
    monthly_search_cap: int        # global cap protecting Places/Bedrock free tiers
    log_retention_days: int
    cors_origins: str
    report_expiry_days: int = 7


TEST = StageConfig(
    stage="test",
    monthly_search_cap=10,
    log_retention_days=7,
    cors_origins="http://localhost:3000",
)

PROD = StageConfig(
    stage="prod",
    monthly_search_cap=30,
    log_retention_days=30,
    cors_origins="https://app.findmeajob.example",  # TODO: real domain
)
