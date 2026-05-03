"""Google GenAI provider (Gemini models)."""

import json
import time
import logging
import threading
from typing import Optional

from google import genai

from .base import LLMProvider, LLMResponse

log = logging.getLogger(__name__)


class GoogleProvider:
    """Provider for Google Gemini models via google-genai SDK."""

    provider_name = "google"

    def __init__(self, api_key: str, model: str = "gemini-3-flash-preview",
                 max_tokens: int = 8192, temperature: float = 0.0):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._api_key = api_key
        self._local = threading.local()

    def _get_client(self):
        # Use a per-thread client – the underlying httpx client is not
        # thread-safe, so sharing one across ThreadPoolExecutor workers causes
        # "Cannot send a request, as the client has been closed" errors.
        client = getattr(self._local, "client", None)
        if client is None:
            client = genai.Client(api_key=self._api_key)
            self._local.client = client
        return client

    def generate(self, system: str, user: str,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None) -> str:
        temp = temperature if temperature is not None else self.temperature
        resp = self._get_client().models.generate_content(
            model=self.model,
            contents=user,
            config=genai.types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens or self.max_tokens,
                temperature=temp,
            ),
        )
        text = resp.text
        if text is None:
            log.warning("Gemini returned None text")
            return ""
        return text

    def generate_json(self, system: str, user: str,
                      max_tokens: Optional[int] = None) -> dict:
        resp = self._get_client().models.generate_content(
            model=self.model,
            contents=user,
            config=genai.types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens or self.max_tokens,
                temperature=self.temperature,
                response_mime_type="application/json",
            ),
        )
        text = resp.text
        if not text:
            raise ValueError("LLM returned empty response for JSON request")
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
        resp = self._get_client().models.generate_content(
            model=self.model,
            contents=user,
            config=genai.types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens or self.max_tokens,
                temperature=temp,
            ),
        )
        duration = time.monotonic() - t0
        text = resp.text or ""

        # Extract token counts from usage metadata
        usage = getattr(resp, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        cached_tokens = getattr(usage, "cached_content_token_count", 0) or 0

        return LLMResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            model=self.model,
            provider="google",
            duration_s=duration,
        )
