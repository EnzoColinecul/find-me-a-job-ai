from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "stage" in body


def test_unhandled_error_includes_cors_for_allowed_origin() -> None:
    from app.main import app

    @app.get("/_test/unhandled")
    def _raise():
        raise RuntimeError("probe")

    response = TestClient(app, raise_server_exceptions=False).get(
        "/_test/unhandled", headers={"Origin": "http://localhost:3000"}
    )
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["x-request-id"] == response.json()["detail"]["request_id"]
