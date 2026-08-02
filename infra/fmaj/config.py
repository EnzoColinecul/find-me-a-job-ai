"""Per-stage configuration. Everything stage-specific lives here."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageConfig:
    stage: str                     # "test" | "prod"
    monthly_search_cap: int        # global cap protecting Places/Bedrock free tiers
    log_retention_days: int
    app_base_url: str              # frontend origin (used for CORS + OAuth callback)
    report_expiry_days: int = 7
    # LLM backend for the agent: "gemini" (Vertex, GCP credits) or "bedrock"
    llm_provider: str = "gemini"
    # Extra allowed callback origins (e.g. deployed preview URL) beyond app_base_url
    extra_callback_urls: list[str] = field(default_factory=list)

    @property
    def cors_origins(self) -> str:
        return self.app_base_url

    @property
    def callback_urls(self) -> list[str]:
        return [f"{self.app_base_url}/auth/callback", *self.extra_callback_urls]

    @property
    def logout_urls(self) -> list[str]:
        return [self.app_base_url]

    # SSM param holding the (non-secret) Google OAuth client id
    @property
    def google_client_id_param(self) -> str:
        return f"/fmaj/{self.stage}/google-client-id"

    # Secrets Manager secret holding the Google OAuth client secret (plaintext)
    @property
    def google_client_secret_name(self) -> str:
        return f"fmaj/{self.stage}/google-client-secret"


TEST = StageConfig(
    stage="test",
    monthly_search_cap=10,
    log_retention_days=7,
    app_base_url="http://localhost:3000",
)

PROD = StageConfig(
    stage="prod",
    monthly_search_cap=30,
    log_retention_days=30,
    app_base_url="https://app.findmeajob.example",  # TODO: real domain
)
