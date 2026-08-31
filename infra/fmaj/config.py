"""Per-stage configuration. Everything stage-specific lives here."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageConfig:
    stage: str  # "test" | "prod"
    monthly_search_cap: int  # global cap protecting Places/Bedrock free tiers
    log_retention_days: int
    app_base_url: str  # frontend origin (used for CORS + OAuth callback)
    report_expiry_days: int = 7
    # LLM backend for the agent: "gemini" (Vertex, GCP credits) or "bedrock"
    llm_provider: str = "gemini"
    # Extra allowed callback origins (e.g. deployed preview URL) beyond app_base_url
    extra_callback_urls: list[str] = field(default_factory=list)
    # Deployed frontend origins (Amplify Hosting), scheme+host with NO trailing
    # slash, e.g. "https://main.d123.amplifyapp.com". One list feeds three places
    # that must agree — Cognito callback URLs, Cognito logout URLs, and the API's
    # CORS allow-list — so adding the Amplify URL is a single edit here. See
    # docs/amplify-deploy.md for the deploy order (the URL only exists after the
    # first Amplify build, so Auth + Api get redeployed once it's known).
    hosting_urls: list[str] = field(default_factory=list)

    @property
    def cors_origins(self) -> str:
        # The API's FMAJ_CORS_ORIGINS. Local dev origin plus every deployed origin.
        return ",".join([self.app_base_url, *self.hosting_urls])

    @property
    def callback_urls(self) -> list[str]:
        return [
            f"{self.app_base_url}/auth/callback",
            *[f"{h}/auth/callback" for h in self.hosting_urls],
            *self.extra_callback_urls,
        ]

    @property
    def logout_urls(self) -> list[str]:
        return [self.app_base_url, *self.hosting_urls]

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
    hosting_urls=["https://main.d3ki9z08su1o3w.amplifyapp.com", "https://develop.d3ki9z08su1o3w.amplifyapp.com"],
)

PROD = StageConfig(
    stage="prod",
    monthly_search_cap=30,
    log_retention_days=30,
    app_base_url="https://app.findmeajob.example",  # TODO: real domain
)
