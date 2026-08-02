"""Test isolation: never inherit the developer's local .env / AWS config.

Without this, `api/.env` (FMAJ_AWS_PROFILE, FMAJ_STATE_MACHINE_ARN) leaks into unit
tests and they try to reach real AWS.
"""
import pytest

from app.settings import settings


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    monkeypatch.setattr(settings, "aws_profile", "", raising=False)
    monkeypatch.setattr(settings, "state_machine_arn", "", raising=False)
    monkeypatch.setattr(settings, "table_name", "test-table", raising=False)
    monkeypatch.setattr(settings, "cognito_user_pool_id", "ap-southeast-2_test",
                        raising=False)
    monkeypatch.setattr(settings, "cognito_client_id", "test-client", raising=False)
