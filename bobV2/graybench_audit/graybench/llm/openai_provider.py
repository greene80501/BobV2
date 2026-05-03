"""OpenAI provider (GPT, o-series models)."""

import json
import time
import logging
from typing import Optional

import openai

from .base import LLMProvider, LLMResponse

log = logging.getLogger(__name__)


class OpenAIProvider:
    """Provider for OpenAI models via the official SDK."""

    provider_name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o",
                 max_tokens: int = 8192, temperature: float = 0.0,
                 base_url: str = None):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def _is_reasoning_model(self) -> bool:
        return (self.model.startswith("o1") or 
                self.model.startswith("o3") or 
                self.model.startswith("o4") or
                self.model.startswith("gpt-5"))

    def generate(self, system: str, user: str,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None) -> str:
        temp = temperature if temperature is not None else self.temperature
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        kwargs = {
            "model": self.model,
            "messages": messages,
        }

        if self._is_reasoning_model():
            # Reasoning models use max_completion_tokens, no temperature
            kwargs["max_completion_tokens"] = max_tokens or self.max_tokens
        else:
            kwargs["max_tokens"] = max_tokens or self.max_tokens
            kwargs["temperature"] = temp

        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def generate_json(self, system: str, user: str,
                      max_tokens: Optional[int] = None) -> dict:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        kwargs = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }

        if self._is_reasoning_model():
            kwargs["max_completion_tokens"] = max_tokens or self.max_tokens
        else:
            kwargs["max_tokens"] = max_tokens or self.max_tokens
            kwargs["temperature"] = self.temperature

        resp = self._client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        text = text.strip()
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
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        kwargs = {
            "model": self.model,
            "messages": messages,
        }

        if self._is_reasoning_model():
            kwargs["max_completion_tokens"] = max_tokens or self.max_tokens
        else:
            kwargs["max_tokens"] = max_tokens or self.max_tokens
            kwargs["temperature"] = temp

        resp = self._client.chat.completions.create(**kwargs)
        duration = time.monotonic() - t0

        usage = resp.usage
        prompt_details = getattr(usage, "prompt_tokens_details", None) if usage else None
        completion_details = getattr(usage, "completion_tokens_details", None) if usage else None
        return LLMResponse(
            text=resp.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cached_tokens=getattr(prompt_details, "cached_tokens", 0) if prompt_details else 0,
            reasoning_tokens=getattr(completion_details, "reasoning_tokens", 0) if completion_details else 0,
            model=self.model,
            provider="openai",
            duration_s=duration,
        )
