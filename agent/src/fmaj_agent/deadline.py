"""Context-local wall-clock deadline shared by providers and outbound tools."""
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_deadline: ContextVar[float | None] = ContextVar("fmaj_deadline", default=None)


def active() -> bool:
    return _deadline.get() is not None


def remaining_seconds(default: float | None = None) -> float | None:
    deadline = _deadline.get()
    if deadline is None:
        return default
    remaining = max(0.0, deadline - time.monotonic())
    return remaining if default is None else min(default, remaining)


def bounded_timeout(default: float) -> float:
    remaining = remaining_seconds(default)
    if remaining is None or remaining <= 0:
        raise TimeoutError("operation deadline exceeded")
    return remaining


def set_deadline(absolute: float | None) -> Token:
    current = _deadline.get()
    if absolute is not None and current is not None:
        absolute = min(absolute, current)
    return _deadline.set(absolute)


def reset_deadline(token: Token) -> None:
    _deadline.reset(token)


@contextmanager
def deadline_after(seconds: float) -> Iterator[None]:
    absolute = time.monotonic() + max(0.0, seconds)
    token = set_deadline(absolute)
    try:
        yield
    finally:
        reset_deadline(token)
