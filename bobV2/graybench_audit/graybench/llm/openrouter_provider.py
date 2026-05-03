"""OpenRouter provider – unified gateway for any model.

Routes any model through OpenRouter's Chat Completions API.
Key behaviors:
- reasoning enabled support
- Preserves reasoning_details across multi-turn calls (pass back unmodified)
- Works with any model via OpenRouter model path
"""

import json
import time
import logging
from typing import Optional

import httpx

from .base import LLMProvider, LLMResponse

log = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider:
    """Routes any model through OpenRouter's unified API."""

    provider_name = "openrouter"

    def __init__(self, api_key: str, model: str = "google/gemini-3-flash-preview",
                 max_tokens: int = 8192, temperature: float = 0.0,
                 reasoning: bool = False):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.reasoning = reasoning
        self._api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/GrayArea-Labs/graybench",
            "X-Title": "GrayBench",
        }
        self._conversation: list[dict] = []

    def _call(self, messages: list[dict], max_tokens: int = None,
              temperature: float = None, json_mode: bool = False) -> dict:
        """Make a raw API call to OpenRouter."""
        payload = {
            "model": self.model,
            "messages": messages,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature

        if self.reasoning:
            payload["reasoning"] = {"enabled": True}

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        with httpx.Client(timeout=300) as client:
            resp = client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def generate(self, system: str, user: str,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None) -> str:
        temp = temperature if temperature is not None else self.temperature
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        result = self._call(messages, max_tokens or self.max_tokens, temp)
        msg = result["choices"][0]["message"]
        text = msg.get("content", "") or ""

        # Store conversation with reasoning_details for potential multi-turn
        self._conversation = messages + [self._build_assistant_msg(msg)]

        return text

    def generate_json(self, system: str, user: str,
                      max_tokens: Optional[int] = None) -> dict:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        result = self._call(messages, max_tokens or self.max_tokens,
                           self.temperature, json_mode=True)
        text = result["choices"][0]["message"].get("content", "") or ""
        text = text.strip()
        if text.startswith("```"):
            first_nl = text.index("\n")
            last_fence = text.rfind("```")
            text = text[first_nl + 1:last_fence].strip()
        return json.loads(text)

    def generate_multi_turn(self, messages: list[dict],
                            max_tokens: Optional[int] = None,
                            temperature: Optional[float] = None) -> dict:
        """Multi-turn generation that preserves reasoning_details.

        Pass back the full message (including reasoning_details) from
        previous turns. OpenRouter will continue reasoning from where
        the model left off.

        Returns the raw assistant message dict (with reasoning_details if present).
        """
        temp = temperature if temperature is not None else self.temperature
        result = self._call(messages, max_tokens or self.max_tokens, temp)
        return result["choices"][0]["message"]

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

        result = self._call(messages, max_tokens or self.max_tokens, temp)
        duration = time.monotonic() - t0

        msg = result["choices"][0]["message"]
        usage = result.get("usage", {})

        return LLMResponse(
            text=msg.get("content", "") or "",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=self.model,
            provider="openrouter",
            duration_s=duration,
            raw={"reasoning_details": msg.get("reasoning_details")} if msg.get("reasoning_details") else {},
        )

    @staticmethod
    def _build_assistant_msg(msg: dict) -> dict:
        """Build an assistant message preserving reasoning_details."""
        result = {
            "role": "assistant",
            "content": msg.get("content"),
        }
        # Preserve reasoning_details unmodified for multi-turn
        if msg.get("reasoning_details"):
            result["reasoning_details"] = msg["reasoning_details"]
        return result

    def continue_conversation(self, user_message: str,
                              max_tokens: Optional[int] = None) -> str:
        """Continue an ongoing conversation, preserving reasoning context.

        Uses stored conversation history with reasoning_details intact.
        """
        self._conversation.append({"role": "user", "content": user_message})

        result = self._call(
            self._conversation,
            max_tokens or self.max_tokens,
            self.temperature,
        )
        msg = result["choices"][0]["message"]
        text = msg.get("content", "") or ""

        self._conversation.append(self._build_assistant_msg(msg))
        return text
