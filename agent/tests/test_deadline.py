import pytest

from fmaj_agent.deadline import bounded_timeout, deadline_after
from fmaj_agent.providers import _with_retry


def test_deadline_bounds_provider_attempt_timeout():
    with deadline_after(0.05):
        timeout = bounded_timeout(10)
        assert 0 < timeout <= 0.05


def test_expired_deadline_prevents_provider_call():
    called = False

    def call(timeout):
        nonlocal called
        called = True

    with deadline_after(0), pytest.raises(TimeoutError, match="deadline exceeded"):
        _with_retry(call, "test")
    assert not called


def test_provider_retry_passes_bounded_timeout(monkeypatch):
    attempts = []

    def call(timeout):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise TimeoutError("read timeout")
        return "ok"

    monkeypatch.setattr("fmaj_agent.providers.time.sleep", lambda _: None)
    monkeypatch.setattr("fmaj_agent.providers.random.random", lambda: 0)
    with deadline_after(1):
        assert _with_retry(call, "test") == "ok"
    assert len(attempts) == 2
    assert all(0 < timeout <= 1 for timeout in attempts)


def test_nested_deadline_cannot_extend_outer_deadline():
    with deadline_after(0.2):
        outer = bounded_timeout(10)
        with deadline_after(10):
            nested = bounded_timeout(10)
        assert nested <= outer
