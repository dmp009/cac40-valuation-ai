import pytest

from cac40val.ai_extraction.llm import AnthropicClient
from cac40val.ai_extraction.models import ExtractionPayload
from cac40val.config import Settings

S = Settings("claude-x", 0.258, 0.02, None, None, "^STOXX50E")


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicClient(S)


def test_extract_returns_tool_input(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    calls = {}

    class Block:
        type = "tool_use"

        def __init__(self):
            self.input = {"guidance": []}

    class Resp:
        def __init__(self):
            self.content = [Block()]

    class Msgs:
        def create(self, **kw):
            calls.update(kw)
            return Resp()

    class Fake:
        def __init__(self, **kw):
            self.messages = Msgs()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", Fake)
    out = AnthropicClient(S).extract("hi", ExtractionPayload)
    assert out == {"guidance": []}
    assert calls["model"] == "claude-x"
    assert calls["tool_choice"] == {"type": "tool", "name": "record_extraction"}
    assert calls["tools"][0]["input_schema"] == ExtractionPayload.model_json_schema()


def test_no_tool_use_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    class Resp:
        def __init__(self):
            self.content = []

    class Fake:
        def __init__(self, **kw):
            self.messages = type("M", (), {"create": lambda s, **kw: Resp()})()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", Fake)
    with pytest.raises(RuntimeError):
        AnthropicClient(S).extract("hi", ExtractionPayload)


def test_truncated_response_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    class Block:
        type = "tool_use"
        input = {"guidance": [{"metric": "organic_growth"}]}

    class Resp:
        stop_reason = "max_tokens"
        content = [Block()]

    class Fake:
        def __init__(self, **kw):
            self.messages = type("M", (), {"create": lambda s, **kw: Resp()})()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", Fake)
    with pytest.raises(RuntimeError, match="max_tokens"):
        AnthropicClient(S).extract("hi", ExtractionPayload)
