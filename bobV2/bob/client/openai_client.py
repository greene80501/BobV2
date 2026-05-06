"""OpenAI Responses API async client for bob.

Handles streaming responses, tool-call buffering, retry logic with
exponential back-off, and yields strongly-typed events to callers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional, Union

from openai import AsyncOpenAI, APIConnectionError, APIError, RateLimitError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed events — imported from bob.llm.client so all clients share the same
# classes and isinstance() checks in turn.py work regardless of which client
# is active.
# ---------------------------------------------------------------------------

from bob.llm.client import (  # noqa: E402
    TextDeltaEvent,
    ToolCallEvent,
    ReasoningDeltaEvent,
    CompletedEvent,
    StreamErrorEvent,
)


def _normalize_responses_input_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items:
        copied = dict(item)
        if copied.get("role") == "user" and isinstance(copied.get("content"), list):
            content_items: list[dict[str, Any]] = []
            for part in copied["content"]:
                if not isinstance(part, dict):
                    continue
                entry = dict(part)
                if entry.get("type") == "input_image":
                    entry.pop("detail", None)
                content_items.append(entry)
            copied["content"] = content_items
        normalized.append(copied)
    return normalized


# ---------------------------------------------------------------------------
# Internal state used while buffering a single tool call
# ---------------------------------------------------------------------------

@dataclass
class _ToolCallBuffer:
    id: str = ""
    name: str = ""
    # Accumulated raw JSON string
    input_json: str = ""


# ---------------------------------------------------------------------------
# BobClient
# ---------------------------------------------------------------------------

class BobClient:
    """Thin async wrapper around the OpenAI Responses API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-5.1-codex-mini",
        enable_prompt_caching: bool = True,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.enable_prompt_caching = enable_prompt_caching

    # ------------------------------------------------------------------
    # Public streaming method
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
        """Stream a single turn through the OpenAI Responses API.

        Parameters
        ----------
        input:
            The conversation history in Responses API format.
        instructions:
            The system/developer instructions string.
        tools:
            JSON-Schema tool definitions to expose to the model.
        max_retries:
            Number of times to retry on transient errors before giving up.
        temperature:
            Sampling temperature (default 1.0).
        max_output_tokens:
            Hard cap on output tokens (None = model default).
        extra_params:
            Additional keyword arguments forwarded verbatim to the API call.
        """
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
    # Internal helpers
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
    ) -> AsyncIterator[
        Union[
            TextDeltaEvent,
            ToolCallEvent,
            ReasoningDeltaEvent,
            CompletedEvent,
            StreamErrorEvent,
        ]
    ]:
        """Retry wrapper around :meth:`_stream_once`."""
        retry_count = 0
        base_delay = 1.0  # seconds

        while True:
            try:
                async for event in self._stream_once(
                    input=input,
                    instructions=instructions,
                    tools=tools,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    extra_params=extra_params,
                ):
                    yield event
                return  # success — exit the retry loop

            except (APIConnectionError, RateLimitError) as exc:
                # Transient errors — retry with back-off
                retry_count += 1
                if retry_count > max_retries:
                    yield StreamErrorEvent(
                        message=f"Exceeded max retries ({max_retries}): {exc}",
                        retry_count=retry_count,
                    )
                    return

                delay = base_delay * (2 ** (retry_count - 1))
                logger.warning(
                    "Transient API error (attempt %d/%d), retrying in %.1fs: %s",
                    retry_count,
                    max_retries,
                    delay,
                    exc,
                )
                yield StreamErrorEvent(
                    message=f"Retrying ({retry_count}/{max_retries}): {exc}",
                    retry_count=retry_count,
                )
                await asyncio.sleep(delay)

            except APIError as exc:
                # Non-transient API error — surface immediately
                yield StreamErrorEvent(
                    message=f"API error: {exc}",
                    retry_count=retry_count,
                )
                return

            except Exception as exc:  # noqa: BLE001
                yield StreamErrorEvent(
                    message=f"Unexpected error: {exc}",
                    retry_count=retry_count,
                )
                return

    async def _stream_once(
        self,
        *,
        input: list[dict[str, Any]],
        instructions: str,
        tools: list[dict[str, Any]],
        temperature: float,
        max_output_tokens: Optional[int],
        extra_params: dict[str, Any],
    ) -> AsyncIterator[
        Union[
            TextDeltaEvent,
            ToolCallEvent,
            ReasoningDeltaEvent,
            CompletedEvent,
            StreamErrorEvent,
        ]
    ]:
        """Perform one streaming request and yield typed events.

        Tool input JSON is buffered per call-index using ``input_json_delta``
        chunks.  A complete :class:`ToolCallEvent` is emitted when the
        corresponding output item is finalised.
        """
        # Map from output-item index → _ToolCallBuffer
        tool_buffers: dict[int, _ToolCallBuffer] = {}

        build_kwargs: dict[str, Any] = {
            "model": self.model,
            "input": _normalize_responses_input_items(input),
            "instructions": instructions,
            "stream": True,
            "temperature": temperature,
            **extra_params,
        }
        
        # Note: OpenAI Responses API does not support cache control parameters
        # Prompt caching is only available in Anthropic's API via LiteLLMClient
        if tools:
            build_kwargs["tools"] = tools
                
        if max_output_tokens is not None:
            build_kwargs["max_output_tokens"] = max_output_tokens

        stream = await self._client.responses.create(**build_kwargs)

        async for raw_event in stream:
            event_type: str = getattr(raw_event, "type", "")

            # ----------------------------------------------------------
            # Text streaming
            # ----------------------------------------------------------
            if event_type == "response.output_text.delta":
                delta: str = getattr(raw_event, "delta", "") or ""
                if delta:
                    yield TextDeltaEvent(delta=delta)

            # ----------------------------------------------------------
            # Reasoning streaming (o-series models)
            # ----------------------------------------------------------
            elif event_type == "response.reasoning_summary_text.delta":
                delta = getattr(raw_event, "delta", "") or ""
                if delta:
                    yield ReasoningDeltaEvent(delta=delta)

            # ----------------------------------------------------------
            # Tool call — function name / id (output item added)
            # ----------------------------------------------------------
            elif event_type == "response.output_item.added":
                item = getattr(raw_event, "item", None)
                if item is not None and getattr(item, "type", "") == "function_call":
                    idx: int = getattr(raw_event, "output_index", 0)
                    buf = _ToolCallBuffer(
                        id=getattr(item, "call_id", "") or getattr(item, "id", ""),
                        name=getattr(item, "name", ""),
                        input_json="",
                    )
                    tool_buffers[idx] = buf

            # ----------------------------------------------------------
            # Tool call — accumulate JSON argument chunks
            # ----------------------------------------------------------
            elif event_type == "response.function_call_arguments.delta":
                idx = getattr(raw_event, "output_index", 0)
                delta = getattr(raw_event, "delta", "") or ""
                if idx in tool_buffers:
                    tool_buffers[idx].input_json += delta

            # ----------------------------------------------------------
            # Tool call — argument stream done, emit ToolCallEvent
            # ----------------------------------------------------------
            elif event_type == "response.function_call_arguments.done":
                idx = getattr(raw_event, "output_index", 0)
                if idx in tool_buffers:
                    buf = tool_buffers.pop(idx)
                    # Finalise the JSON string (may have arrived via .done)
                    final_json: str = getattr(raw_event, "arguments", buf.input_json)
                    try:
                        parsed_input: dict[str, Any] = json.loads(final_json) if final_json else {}
                    except json.JSONDecodeError:
                        logger.warning(
                            "Failed to parse tool input JSON for %s: %r",
                            buf.name,
                            final_json,
                        )
                        parsed_input = {"_raw": final_json}
                    yield ToolCallEvent(id=buf.id, name=buf.name, input=parsed_input)

            # ----------------------------------------------------------
            # Response completed — emit usage
            # ----------------------------------------------------------
            elif event_type == "response.completed":
                response = getattr(raw_event, "response", None)
                if response is not None:
                    usage = getattr(response, "usage", None)
                    if usage is not None:
                        yield CompletedEvent(
                            input_tokens=getattr(usage, "input_tokens", 0),
                            output_tokens=getattr(usage, "output_tokens", 0),
                            total_tokens=getattr(usage, "total_tokens", 0),
                            cached_input_tokens=getattr(usage, "cached_input_tokens", 0),
                        )
                    else:
                        yield CompletedEvent(
                            input_tokens=0,
                            output_tokens=0,
                            total_tokens=0,
                            cached_input_tokens=0,
                        )

            # ----------------------------------------------------------
            # Error event from the API
            # ----------------------------------------------------------
            elif event_type == "error":
                message: str = getattr(raw_event, "message", str(raw_event))
                yield StreamErrorEvent(message=message, retry_count=0)
                return

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    async def list_models(self) -> list[str]:
        """Return a sorted list of model IDs available on this API endpoint."""
        response = await self._client.models.list()
        return sorted(m.id for m in response.data)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()

    # Async context manager support
    async def __aenter__(self) -> "BobClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
