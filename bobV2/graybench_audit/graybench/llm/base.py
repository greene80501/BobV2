"""Base protocol and types for LLM providers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol, Optional, runtime_checkable


@dataclass
class LLMResponse:
    """Unified response with token tracking."""
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    model: str = ""
    provider: str = ""
    duration_s: float = 0.0
    raw: dict = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """All LLM providers must implement these methods."""

    provider_name: str

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Single-turn text generation. Returns the assistant's text."""
        ...

    def generate_json(
        self,
        system: str,
        user: str,
        max_tokens: Optional[int] = None,
    ) -> dict:
        """Generate and parse a JSON response."""
        ...

    def generate_with_tracking(
        self,
        system: str,
        user: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs,
    ) -> LLMResponse:
        """Generate with full token/cost tracking. Returns LLMResponse."""
        ...
