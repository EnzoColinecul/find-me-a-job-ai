from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration. In Lambda these come from stage env vars set by CDK."""

    stage: str = "test"
    aws_region: str = "ap-southeast-2"
    aws_profile: str = ""  # local dev only; empty in Lambda (role creds)
    table_name: str = "fmaj-test-main"
    reports_bucket: str = "fmaj-test-reports"
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    state_machine_arn: str = ""
    cors_origins: str = "http://localhost:3000"

    # Roles a user may run in ONE search. PoC = 1; raise when subscriptions land.
    # Single source of truth: the API validates against it and the frontend fetches
    # it from GET /config, so changing this value alone changes the whole product.
    max_roles: int = 1
    max_radius_km: float = 10.0

    model_config = {"env_prefix": "FMAJ_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
