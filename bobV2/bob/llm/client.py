"""LiteLLM-based multi-provider async streaming client for Bob.

Drop-in replacement for bob.client.openai_client.BobClient.

Key differences from the old client:
- Uses litellm.acompletion() instead of the OpenAI Responses API.
- Supports 100+ providers by changing config.model (e.g. "anthropic/claude-3-5-sonnet").
- Converts Bob's internal Responses-API history format → Chat Completions
  messages internally, so turn.py needs no changes.
- Yields the exact same typed events: TextDeltaEvent, ToolCallEvent,
  ReasoningDeltaEvent, CompletedEvent, StreamErrorEvent.

Re-exports those event types so existing imports from openai_client still work:

    from bob.llm.client import (
        TextDeltaEvent, ToolCallEvent, ReasoningDeltaEvent,
        CompletedEvent, StreamErrorEvent, LiteLLMClient,
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Typed events — identical to those in openai_client.py so turn.py is
# unaffected. We simply re-define them here; session.py points at this module.
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass
class TextDeltaEvent:
    """A streaming text chunk from the model."""
    delta: str


@dataclass
class ToolCallEvent:
    """A fully-assembled tool call (emitted once complete)."""
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ReasoningDeltaEvent:
    """A streaming reasoning/thinking token."""
    delta: str


@dataclass
class CompletedEvent:
    """Emitted once the full response is done. Carries token usage."""
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass
class StreamErrorEvent:
    """Emitted when a (possibly-transient) error occurs during streaming."""
    message: str
    retry_count: int


# ---------------------------------------------------------------------------
# History format conversion: Responses API → Chat Completions
# ---------------------------------------------------------------------------

def _to_chat_messages(instructions: str, items: list[dict]) -> list[dict]:
    """Convert Bob's Responses-API history items to Chat Completions messages.

    Bob stores history in OpenAI Responses API shape:
        {"role": "user",      "content": [{"type": "input_text", "text": "…"}]}
        {"role": "assistant", "content": [{"type": "output_text", "text": "…"}]}
        {"type": "function_call",        "call_id": "…", "name": "…", "arguments": "…"}
        {"type": "function_call_output", "call_id": "…", "output": "…"}

    This converts to OpenAI Chat Completions shape that LiteLLM accepts:
        {"role": "system",    "content": "…"}
        {"role": "user",      "content": "…"}
        {"role": "assistant", "content": "…", "tool_calls": […]}   ← merged
        {"role": "tool",      "tool_call_id": "…", "content": "…"}
    """
    messages: list[dict] = []
    if instructions:
        messages.append({"role": "system", "content": instructions})

    i = 0
    while i < len(items):
        item = items[i]
        role = item.get("role", "")
        itype = item.get("type", "")

        # ── User message ─────────────────────────────────────────────────
        if role == "user":
            content = item.get("content", [])
            if isinstance(content, list):
                has_image = any(c.get("type") == "input_image" for c in content)
                if has_image:
                    parts: list[dict] = []
                    for c in content:
                        if c.get("type") == "input_text":
                            parts.append({"type": "text", "text": c.get("text", "")})
                        elif c.get("type") == "input_image":
                            parts.append({
                                "type": "image_url",
                                "image_url": {"url": c.get("image_url", "")},
                            })
                    messages.append({"role": "user", "content": parts})
                else:
                    text = "\n".join(
                        c.get("text", "") for c in content
                        if c.get("type") == "input_text"
                    )
                    messages.append({"role": "user", "content": text})
            else:
                messages.append({"role": "user", "content": str(content or "")})
            i += 1

        # ── Assistant text message — look ahead for tool calls ───────────
        elif role == "assistant":
            content_list = item.get("content", [])
            if isinstance(content_list, list):
                text = "\n".join(
                    c.get("text", "") for c in content_list
                    if c.get("type") == "output_text"
                )
            else:
                text = str(content_list or "")

            # Greedily consume consecutive function_call items that belong
            # to this same model response.
            tool_calls: list[dict] = []
            j = i + 1
            while j < len(items) and items[j].get("type") == "function_call":
                fc = items[j]
                tool_calls.append({
                    "id": fc["call_id"],
                    "type": "function",
                    "function": {
                        "name": fc["name"],
                        "arguments": fc.get("arguments", "{}"),
                    },
                })
                j += 1

            if tool_calls:
                msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": tool_calls,
                }
                messages.append(msg)
                i = j
            else:
                messages.append({"role": "assistant", "content": text})
                i += 1

        # ── Orphaned function_call (no preceding assistant text) ─────────
        elif itype == "function_call":
            tool_calls = []
            while i < len(items) and items[i].get("type") == "function_call":
                fc = items[i]
                tool_calls.append({
                    "id": fc["call_id"],
                    "type": "function",
                    "function": {
                        "name": fc["name"],
                        "arguments": fc.get("arguments", "{}"),
                    },
                })
                i += 1
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls,
            })

        # ── Tool result ───────────────────────────────────────────────────
        elif itype == "function_call_output":
            messages.append({
                "role": "tool",
                "tool_call_id": item["call_id"],
                "content": str(item.get("output", "")),
            })
            i += 1

        else:
            i += 1  # skip unknown items

    return messages


# ---------------------------------------------------------------------------
# LiteLLMClient
# ---------------------------------------------------------------------------

class LiteLLMClient:
    """Multi-provider LLM client backed by LiteLLM.

    Accepts the same stream_turn() signature as BobClient and yields the
    same typed events so bob/core/turn.py requires no changes.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "gpt-4o",
        base_url: Optional[str] = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._base_url = base_url
        self._configure_litellm()

    def _configure_litellm(self) -> None:
        try:
            import litellm
            litellm.drop_params = True       # silently ignore unsupported params
            litellm.suppress_debug_info = True
        except ImportError:
            pass

    # ------------------------------------------------------------------
    # Public API — identical signature to BobClient.stream_turn()
    # ------------------------------------------------------------------

    def stream_turn(
        self,
        input: list[dict[str, Any]],
        instructions: str,
        tools: list[dict[str, Any]],
        max_retries: int = 3,
        *,
        temperature: float = 1.0,
        max_output_tokens: Optional[int] = None,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[
        Union[
            TextDeltaEvent,
            ToolCallEvent,
            ReasoningDeltaEvent,
            CompletedEvent,
            StreamErrorEvent,
        ]
    ]:
        return self._stream_with_retry(
            input=input,
            instructions=instructions,
            tools=tools,
            max_retries=max_retries,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            extra_params=extra_params or {},
        )

    # ------------------------------------------------------------------
    # Retry wrapper
    # ------------------------------------------------------------------

    async def _stream_with_retry(
        self,
        *,
        input: list[dict[str, Any]],
        instructions: str,
        tools: list[dict[str, Any]],
        max_retries: int,
        temperature: float,
        max_output_tokens: Optional[int],
        extra_params: dict[str, Any],
    ) -> AsyncIterator:
        retry_count = 0
        base_delay = 1.0

        while True:
            try:
                async for ev in self._stream_once(
                    input=input,
                    instructions=instructions,
                    tools=tools,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    extra_params=extra_params,
                ):
                    yield ev
                return

            except Exception as exc:
                # Classify as transient or fatal
                exc_name = type(exc).__name__.lower()
                is_transient = any(k in exc_name for k in (
                    "ratelimit", "connection", "timeout", "serviceunavailable",
                    "overloaded", "apierror",
                ))

                if is_transient and retry_count < max_retries:
                    retry_count += 1
                    delay = base_delay * (2 ** (retry_count - 1))
                    logger.warning(
                        "Transient error (attempt %d/%d), retrying in %.1fs: %s",
                        retry_count, max_retries, delay, exc,
                    )
                    yield StreamErrorEvent(
                        message=f"Retrying ({retry_count}/{max_retries}): {exc}",
                        retry_count=retry_count,
                    )
                    await asyncio.sleep(delay)
                else:
                    yield StreamErrorEvent(
                        message=str(exc),
                        retry_count=retry_count,
                    )
                    return

    # ------------------------------------------------------------------
    # Single streaming attempt
    # ------------------------------------------------------------------

    async def _stream_once(
        self,
        *,
        input: list[dict[str, Any]],
        instructions: str,
        tools: list[dict[str, Any]],
        temperature: float,
        max_output_tokens: Optional[int],
        extra_params: dict[str, Any],
    ) -> AsyncIterator:
        try:
            import litellm
        except ImportError as exc:
            yield StreamErrorEvent(
                message="litellm is not installed. Run: pip install litellm",
                retry_count=0,
            )
            raise StopAsyncIteration from exc

        messages = _to_chat_messages(instructions, input)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            **extra_params,
        }

        # Optional params
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens
        if self._base_url:
            kwargs["base_url"] = self._base_url
        if self._api_key:
            kwargs["api_key"] = self._api_key

        # Request usage in the final streaming chunk (OpenAI + some others)
        kwargs["stream_options"] = {"include_usage": True}

        # ── Accumulate tool-call fragments by index ─────────────────────
        # { index: {"id": str, "name": str, "args": str} }
        tool_buffers: dict[int, dict[str, str]] = {}
        final_usage: Any = None

        response = await litellm.acompletion(**kwargs)

        async for chunk in response:
            # Some providers send a usage-only final chunk with no choices
            if not getattr(chunk, "choices", None):
                u = getattr(chunk, "usage", None)
                if u:
                    final_usage = u
                continue

            choice = chunk.choices[0]
            delta = getattr(choice, "delta", None)
            finish_reason = getattr(choice, "finish_reason", None)

            if delta is None:
                continue

            # ── Text delta ───────────────────────────────────────────────
            content = getattr(delta, "content", None)
            if content:
                yield TextDeltaEvent(delta=content)

            # ── Reasoning / thinking (Anthropic extended thinking) ───────
            thinking = getattr(delta, "thinking", None)
            if thinking:
                yield ReasoningDeltaEvent(delta=thinking)

            # ── Tool-call deltas ─────────────────────────────────────────
            tc_deltas = getattr(delta, "tool_calls", None)
            if tc_deltas:
                for tc in tc_deltas:
                    idx: int = getattr(tc, "index", 0)
                    if idx not in tool_buffers:
                        tool_buffers[idx] = {"id": "", "name": "", "args": ""}
                    buf = tool_buffers[idx]
                    if getattr(tc, "id", None):
                        buf["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn:
                        fn_name = getattr(fn, "name", None)
                        fn_args = getattr(fn, "arguments", None)
                        if fn_name:
                            buf["name"] += fn_name
                        if fn_args:
                            buf["args"] += fn_args

            # ── Capture usage when it arrives in-stream ──────────────────
            u = getattr(chunk, "usage", None)
            if u and (getattr(u, "prompt_tokens", None) or getattr(u, "total_tokens", None)):
                final_usage = u

        # ── After stream ends: emit completed tool calls ─────────────────
        for idx in sorted(tool_buffers):
            buf = tool_buffers[idx]
            raw_args = buf["args"]
            try:
                parsed: dict[str, Any] = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                logger.warning("Failed to parse tool args for %r: %r", buf["name"], raw_args)
                parsed = {"_raw": raw_args}
            yield ToolCallEvent(id=buf["id"], name=buf["name"], input=parsed)

        # ── Emit usage ────────────────────────────────────────────────────
        if final_usage is not None:
            yield CompletedEvent(
                input_tokens=int(getattr(final_usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(final_usage, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(final_usage, "total_tokens", 0) or 0),
            )
        else:
            # Provider didn't return usage — emit zeros so callers don't break
            yield CompletedEvent(input_tokens=0, output_tokens=0, total_tokens=0)

    # ------------------------------------------------------------------
    # Utility methods (mirror BobClient API)
    # ------------------------------------------------------------------

    async def list_models(self) -> list[str]:
        """Return available model IDs (best-effort — not all providers support this)."""
        try:
            import litellm
            models = litellm.model_list or []
            return sorted(str(m) for m in models)
        except Exception:
            return []

    async def close(self) -> None:
        """No-op — LiteLLM uses per-request httpx clients."""

    async def __aenter__(self) -> "LiteLLMClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
