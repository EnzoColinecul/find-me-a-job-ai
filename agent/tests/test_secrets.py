"""Secrets resolution: env-var fallback path (no AWS calls)."""
import fmaj_agent.secrets as secrets


def test_places_key_env_fallback(monkeypatch) -> None:
    monkeypatch.setenv("FMAJ_PLACES_KEY", "env-places")
    assert secrets.places_api_key() == "env-places"


def test_adzuna_env_fallback(monkeypatch) -> None:
    monkeypatch.setenv("FMAJ_ADZUNA_APP_ID", "id123")
    monkeypatch.setenv("FMAJ_ADZUNA_APP_KEY", "key456")
    assert secrets.adzuna_credentials() == ("id123", "key456")


def test_serpapi_env_fallback(monkeypatch) -> None:
    monkeypatch.setenv("FMAJ_SERPAPI_KEY", "env-serp")
    assert secrets.serpapi_key() == "env-serp"
