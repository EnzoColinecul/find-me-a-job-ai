import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Export .env into os.environ BEFORE anything imports fmaj_agent: pydantic-settings
# only feeds its own fields, but third-party libs read os.environ directly
# (google.auth -> GOOGLE_APPLICATION_CREDENTIALS, fmaj_agent.config -> FMAJ_*).
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE)

# Google's SDK needs an absolute path; .env conveniently holds a relative one.
_gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if _gac and not os.path.isabs(_gac):
    resolved = (_ENV_FILE.parent / _gac).resolve()
    if resolved.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(resolved)


class Settings(BaseSettings):
    """Runtime configuration. In Lambda these come from stage env vars set by CDK."""

    stage: str = "test"
    aws_region: str = "ap-southeast-2"
    aws_profile: str = ""  # local dev only; empty in Lambda (role creds)
    table_name: str = "fmaj-test-main"
    # Matches the CDK-created bucket (data_stack: fmaj-{stage}-reports-<acct>).
    # Override per stage via FMAJ_REPORTS_BUCKET.
    reports_bucket: str = "fmaj-test-reports-418862088910"
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    state_machine_arn: str = ""
    cors_origins: str = "http://localhost:3000"

    # Roles a user may run in ONE search. PoC = 1; raise when subscriptions land.
    # Single source of truth: the API validates against it and the frontend fetches
    # it from GET /config, so changing this value alone changes the whole product.
    max_roles: int = 1
    max_radius_km: float = 10.0

    # Ceiling across ALL users for a calendar month. This is the blast-radius
    # control: the free-search quota stops one person running up a bill, this
    # stops a hundred people doing it one search each. Sized against the real
    # binding constraint — Places Enterprise Details, 1K calls/month free, which
    # is ~25-33 searches (see "Cost discipline" in CLAUDE.md). 0 = unlimited.
    global_monthly_searches: int = 30

    # One search at a time per user. Held as a lease rather than a flag that
    # something else has to clear: a crashed pipeline would otherwise lock the
    # user out permanently, and there is no process that reliably unsets it.
    # Generous next to a real search (minutes), short next to a stuck one.
    search_lease_minutes: int = 15

    model_config = {"env_prefix": "FMAJ_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
