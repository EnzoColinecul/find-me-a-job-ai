"""Suite-wide fixtures."""
import pytest

from fmaj_agent import observability


@pytest.fixture(autouse=True)
def _tracing_off():
    """Tests never talk to Langfuse Cloud.

    Without this, the Langfuse keys in the developer's repo-root `.env` would be
    picked up and every test run would export spans to the real project.
    Tests that exercise tracing install an in-memory client themselves.
    """
    observability.disable()
    yield
    observability.disable()
