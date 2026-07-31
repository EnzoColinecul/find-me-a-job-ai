"""Auth tests that don't require live Cognito keys.

Full end-to-end token verification is covered by manual testing against the deployed
pool (see docs/google-login-setup.md). Here we assert the guard rails.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_me_requires_token() -> None:
    resp = client.get("/me")
    assert resp.status_code == 401


def test_me_rejects_garbage_token() -> None:
    resp = client.get("/me", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert resp.status_code == 401
