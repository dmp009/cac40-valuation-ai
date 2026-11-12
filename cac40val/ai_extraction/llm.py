"""LLM client abstraction and the Anthropic implementation."""

import logging
import os
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from cac40val.config import Settings

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "extract_v2.md"
TOOL_NAME = "record_extraction"


class LLMClient(Protocol):
    def extract(self, prompt: str, schema: type[BaseModel]) -> dict: ...


class AnthropicClient:
    def __init__(self, settings: Settings):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set; cannot call the Anthropic API")
        import anthropic

        self._client = anthropic.Anthropic(api_key=key)
        self._model = settings.llm_model

    def extract(self, prompt: str, schema: type[BaseModel]) -> dict:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=8000,
            tools=[
                {
                    "name": TOOL_NAME,
                    "description": "Record the structured facts extracted from the report pages.",
                    "input_schema": schema.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": prompt}],
        )
        if getattr(resp, "stop_reason", None) == "max_tokens":
            raise RuntimeError(
                "Anthropic response hit max_tokens; the tool input is truncated and was discarded"
            )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                return dict(block.input)
        raise RuntimeError("Anthropic response contained no tool_use block")
