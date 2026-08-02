"""Provider message-normalization tests (no network — pure conversion logic)."""
from fmaj_agent.providers import BedrockProvider, ToolUse


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
