from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration. In Lambda these come from stage env vars set by CDK."""

    stage: str = "test"
    aws_region: str = "ap-southeast-2"
    table_name: str = "fmaj-test-main"
    reports_bucket: str = "fmaj-test-reports"
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    state_machine_arn: str = ""
    cors_origins: str = "http://localhost:3000"

    model_config = {"env_prefix": "FMAJ_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
