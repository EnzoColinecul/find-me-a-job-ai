"""Tolerant JSON parsing — models wrap output in fences/prose or return nothing."""
from fmaj_agent.interpret import _parse_json


def test_plain_json() -> None:
    assert _parse_json('{"roles": []}') == {"roles": []}


def test_markdown_fenced_json() -> None:
    assert _parse_json('```json\n{"roles": [{"label": "chef"}]}\n```') == {
        "roles": [{"label": "chef"}]
    }


def test_json_wrapped_in_prose() -> None:
    raw = 'Here you go:\n{"roles": [{"label": "barista"}]}\nHope that helps!'
    assert _parse_json(raw)["roles"][0]["label"] == "barista"


def test_empty_and_none_return_none() -> None:
    # Gemini 3 can return empty text if thinking consumes the token budget
    assert _parse_json("") is None
    assert _parse_json("   ") is None
    assert _parse_json(None) is None


def test_no_json_returns_none() -> None:
    assert _parse_json("I'm sorry, I can't help with that.") is None
