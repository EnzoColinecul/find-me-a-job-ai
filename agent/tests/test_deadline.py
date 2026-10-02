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
    with deadline_after(5):
        assert _with_retry(call, "test") == "ok"
    assert len(attempts) == 2
    assert all(0 < timeout <= 5 for timeout in attempts)


def test_nested_deadline_cannot_extend_outer_deadline():
    with deadline_after(0.2):
        outer = bounded_timeout(10)
        with deadline_after(10):
            nested = bounded_timeout(10)
        assert nested <= outer


def test_model_timeout_is_longer_than_ten_seconds_but_bounded(monkeypatch):
    from fmaj_agent import config

    monkeypatch.setattr(config, "MODEL_CALL_SECONDS", 30)
    assert _with_retry(lambda timeout: timeout, "test") == 30
    with deadline_after(17):
        assert 10 < _with_retry(lambda timeout: timeout, "test") <= 17


@pytest.mark.parametrize("code", [408, 429, 499, 500, 502, 503, 504])
def test_vertex_transient_status_has_one_bounded_retry(monkeypatch, code):
    from google.genai.errors import APIError

    clock = [100.0]
    sleeps, timeouts = [], []
    monkeypatch.setattr("fmaj_agent.deadline.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("fmaj_agent.providers.random.random", lambda: 0)

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    def call(timeout):
        timeouts.append(timeout)
        clock[0] += 2
        raise APIError(code, {"error": {"message": "transient"}})

    monkeypatch.setattr("fmaj_agent.providers.time.sleep", sleep)
    with deadline_after(12), pytest.raises(APIError):
        _with_retry(call, "test")
    assert sleeps == [1]
    assert timeouts == [12, 9]


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_vertex_permanent_errors_are_not_retried(monkeypatch, code):
    from google.genai.errors import APIError

    attempts = []
    monkeypatch.setattr("fmaj_agent.providers.time.sleep", lambda _: pytest.fail("unexpected backoff"))

    def call(timeout):
        attempts.append(timeout)
        raise APIError(code, {"error": {"message": "invalid timeout setting"}})

    with pytest.raises(APIError):
        _with_retry(call, "test")
    assert len(attempts) == 1


def test_retry_does_not_start_without_time_for_backoff_and_request(monkeypatch):
    attempts = []
    monkeypatch.setattr("fmaj_agent.providers.time.sleep", lambda _: pytest.fail("unexpected backoff"))

    def call(timeout):
        attempts.append(timeout)
        raise TimeoutError("request timeout")

    with deadline_after(1.5), pytest.raises(TimeoutError):
        _with_retry(call, "test")
    assert len(attempts) == 1


@pytest.mark.parametrize("value", ["0", "-2", "nan", "inf", "oops"])
def test_invalid_request_timeout_keeps_finite_default(monkeypatch, value):
    from fmaj_agent import config

    monkeypatch.setenv("FMAJ_TEST_TIMEOUT", value)
    assert config._timeout("FMAJ_TEST_TIMEOUT", 30) == 30


def test_request_timeout_accepts_positive_override(monkeypatch):
    from fmaj_agent import config

    monkeypatch.setenv("FMAJ_TEST_TIMEOUT", "25.5")
    assert config._timeout("FMAJ_TEST_TIMEOUT", 30) == 25.5
