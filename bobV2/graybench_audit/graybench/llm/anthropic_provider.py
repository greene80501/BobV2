"""Anthropic provider (Claude models)."""

import json
import time
import logging
from typing import Optional

import anthropic

from .base import LLMProvider, LLMResponse

log = logging.getLogger(__name__)


class AnthropicProvider:
    """Provider for Anthropic Claude models via the official SDK."""

    provider_name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514",
                 max_tokens: int = 8192, temperature: float = 0.0):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, system: str, user: str,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None) -> str:
        temp = temperature if temperature is not None else self.temperature
        resp = self._client.messages.create(
            model=self.model,
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens or self.max_tokens,
            temperature=temp,
        )
        # Extract text from content blocks
        text_parts = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
        return "".join(text_parts)

    def generate_json(self, system: str, user: str,
                      max_tokens: Optional[int] = None) -> dict:
        # Anthropic doesn't have a native JSON mode. Use prefill approach.
        system_with_json = system + "\n\nRespond with valid JSON only. No markdown fences."
        resp = self._client.messages.create(
            model=self.model,
            system=system_with_json,
            messages=[
                {"role": "user", "content": user},
                {"role": "assistant", "content": "{"},
            ],
            max_tokens=max_tokens or self.max_tokens,
            temperature=self.temperature,
        )
        text = ""
        for block in resp.content:
            if block.type == "text":
                text += block.text
        # Prepend the prefilled '{'
        text = "{" + text.strip()
        if text.startswith("```"):
            first_nl = text.index("\n")
            last_fence = text.rfind("```")
            text = text[first_nl + 1:last_fence].strip()
        return json.loads(text)

    def generate_with_tracking(self, system: str, user: str,
                                max_tokens: Optional[int] = None,
                                temperature: Optional[float] = None,
                                **kwargs) -> LLMResponse:
        t0 = time.monotonic()
        temp = temperature if temperature is not None else self.temperature
        resp = self._client.messages.create(
            model=self.model,
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens or self.max_tokens,
            temperature=temp,
        )
        duration = time.monotonic() - t0

        text_parts = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)

        return LLMResponse(
            text="".join(text_parts),
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cached_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
            model=self.model,
            provider="anthropic",
            duration_s=duration,
        )
