"""Auth tests that don't require live Cognito keys.

Full end-to-end token verification is covered by manual testing against the deployed
pool (see docs/google-login-setup.md). Here we assert the guard rails.
"""
from types import SimpleNamespace

from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app import auth
from app.main import app

client = TestClient(app)


def test_me_requires_token() -> None:
    resp = client.get("/me")
    assert resp.status_code == 401


def test_me_rejects_garbage_token() -> None:
    resp = client.get("/me", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert resp.status_code == 401


def test_auth_accepts_only_configured_cognito_client_audiences(monkeypatch) -> None:
    monkeypatch.setattr(auth.settings, "cognito_client_id", "web-client,smoke-client")
    monkeypatch.setattr(
        auth,
        "_jwks_client",
        lambda: SimpleNamespace(get_signing_key_from_jwt=lambda _token: SimpleNamespace(key="key")),
    )
    captured = {}

    def decode(_token, _key, **kwargs):
        captured.update(kwargs)
        return {"sub": "test-user", "email": "smoke@example.test", "token_use": "id"}

    monkeypatch.setattr(auth.jwt, "decode", decode)
    user = auth.require_user(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="signed-token")
    )

    assert user.sub == "test-user"
    assert captured["audience"] == ["web-client", "smoke-client"]
