"""Moonshot provider (Kimi models, OpenAI-compatible API)."""

import json
import time
import logging
from typing import Optional

import openai

from .base import LLMProvider, LLMResponse

log = logging.getLogger(__name__)

MOONSHOT_BASE_URL = "https://api.moonshot.cn/v1"


class MoonshotProvider:
    """Provider for Moonshot Kimi models via OpenAI-compatible API."""

    provider_name = "moonshot"

    def __init__(self, api_key: str, model: str = "kimi-k2.5",
                 max_tokens: int = 8192, temperature: float = 0.0,
                 base_url: str = None):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url or MOONSHOT_BASE_URL,
        )

    def _is_thinking(self) -> bool:
        return "thinking" in self.model

    def generate(self, system: str, user: str,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None) -> str:
        temp = temperature if temperature is not None else self.temperature
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=temp,
        )
        return resp.choices[0].message.content or ""

    def generate_json(self, system: str, user: str,
                      max_tokens: Optional[int] = None) -> dict:
        messages = [
            {"role": "system", "content": system + "\n\nRespond with valid JSON only."},
            {"role": "user", "content": user},
        ]
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=self.temperature,
            response_format={"type": "json_object"},
        )
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
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=temp,
        )
        duration = time.monotonic() - t0
        usage = resp.usage

        return LLMResponse(
            text=resp.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=self.model,
            provider="moonshot",
            duration_s=duration,
        )
