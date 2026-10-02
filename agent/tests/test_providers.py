"""Provider message-normalization tests (no network — pure conversion logic)."""
from fmaj_agent.providers import BedrockProvider, ToolUse


def test_gemini_wire_timeout_and_sdk_retries_are_explicit(monkeypatch):
    from types import SimpleNamespace

    from fmaj_agent import config
    from fmaj_agent.deadline import deadline_after
    from fmaj_agent.providers import GeminiProvider

    captured = []

    def generate_content(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(candidates=[], usage_metadata=None)

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(config, "MODEL_CALL_SECONDS", 30)
    with deadline_after(19):
        provider._complete("", [{"role": "user", "text": "hello"}],
                           model="test", use_tools=False, json_mode=True)
    options = captured[0]["config"].http_options
    assert 10000 < options.timeout <= 19000
    assert options.retry_options.attempts == 1
    assert captured[0]["config"].response_mime_type == "application/json"


def test_bedrock_message_conversion() -> None:
    msgs = [
        {"role": "user", "text": "hello"},
        {"role": "assistant", "text": "thinking",
         "tool_uses": [ToolUse("t1", "fetch_url", {"url": "https://x"})]},
        {"role": "tool", "results": [{"id": "t1", "name": "fetch_url",
                                      "output": {"ok": True, "text": "hi"}}]},
    ]
    out = BedrockProvider._to_messages(msgs)
    assert out[0] == {"role": "user", "content": [{"text": "hello"}]}
    # assistant turn keeps text + toolUse
    assert any("toolUse" in c for c in out[1]["content"])
    assert out[1]["content"][0]["text"] == "thinking"
    # tool result becomes a user turn with toolResult
    assert out[2]["role"] == "user"
    assert out[2]["content"][0]["toolResult"]["toolUseId"] == "t1"
    assert out[2]["content"][0]["toolResult"]["content"][0]["json"]["ok"] is True
