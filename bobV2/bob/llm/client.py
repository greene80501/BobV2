"""LiteLLM-based multi-provider async streaming client for Bob.

Drop-in replacement for bob.client.openai_client.BobClient.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
import os
import re
from typing import Any, AsyncIterator, Optional, Union

logger = logging.getLogger(__name__)
_ENV_OVERRIDE_LOCK: asyncio.Lock | None = None

_SAFE_TOOL_NAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]*$')


def _make_tool_name_safe(name: str) -> str:
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    if not safe or not safe[0].isalpha():
        safe = 't_' + safe
    return safe[:64]


def _normalize_tools_to_chat_format(tools: list[dict]) -> list[dict]:
    """Convert flat Responses-API tools to Chat-Completions nested format.

    Flat:   {"type": "function", "name": "...", "description": "...", "parameters": {...}}
    Nested: {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
    """
    out = []
    for t in tools:
        if "function" not in t and "name" in t:
            out.append({
                "type": "function",
                "function": {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {}),
                },
            })
        else:
            out.append(t)
    return out


def _sanitize_tools(tools: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Return (sanitized_tools, safe->original map for any renamed tools).

    Works on nested Chat-Completions format only; call _normalize_tools_to_chat_format first.
    """
    name_map: dict[str, str] = {}
    out = []
    for t in tools:
        fn = dict(t.get("function") or {})
        orig = fn.get("name", "")
        if orig and not _SAFE_TOOL_NAME_RE.match(orig):
            safe = _make_tool_name_safe(orig)
            name_map[safe] = orig
            fn["name"] = safe
            t = {**t, "function": fn}
        out.append(t)
    return out, name_map


def _patch_message_tool_names(messages: list[dict], name_map: dict[str, str]) -> list[dict]:
    """Replace original tool names in history with their sanitized equivalents."""
    if not name_map:
        return messages
    orig_to_safe = {v: k for k, v in name_map.items()}
    out = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            new_tcs = []
            for tc in msg["tool_calls"]:
                fn = dict(tc.get("function") or {})
                fn_name = fn.get("name", "")
                if fn_name in orig_to_safe:
                    fn["name"] = orig_to_safe[fn_name]
                    tc = {**tc, "function": fn}
                new_tcs.append(tc)
            msg = {**msg, "tool_calls": new_tcs}
        out.append(msg)
    return out


@dataclass
class TextDeltaEvent:
    delta: str


@dataclass
class ToolCallEvent:
    id: str
    name: str
    input: dict[str, Any]
    reasoning_content: str = ""


@dataclass
class ReasoningDeltaEvent:
    delta: str


@dataclass
class CompletedEvent:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int = 0


@dataclass
class StreamErrorEvent:
    message: str
    retry_count: int


def _get_env_override_lock() -> asyncio.Lock:
    global _ENV_OVERRIDE_LOCK
    if _ENV_OVERRIDE_LOCK is None:
        _ENV_OVERRIDE_LOCK = asyncio.Lock()
    return _ENV_OVERRIDE_LOCK


@asynccontextmanager
async def _temporary_env(overrides: dict[str, str]):
    if not overrides:
        yield
        return

    lock = _get_env_override_lock()
    async with lock:
        previous: dict[str, str | None] = {}
        try:
            for key, value in overrides.items():
                previous[key] = os.environ.get(key)
                os.environ[key] = value
            yield
        finally:
            for key, old_value in previous.items():
                if old_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old_value


def _to_chat_messages(
    instructions: str,
    items: list[dict],
    model: str = "",
    enable_caching: bool = False,
) -> list[dict]:
    """Convert Bob's Responses-style history into chat-completions messages."""
    messages: list[dict] = []
    if instructions:
        is_anthropic = "claude" in model.lower()
        if is_anthropic and enable_caching:
            messages.append(
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": instructions,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            )
        else:
            messages.append({"role": "system", "content": instructions})

    i = 0
    while i < len(items):
        item = items[i]
        role = item.get("role", "")
        itype = item.get("type", "")

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
                            parts.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": c.get("image_url", "")},
                                }
                            )
                    messages.append({"role": "user", "content": parts})
                else:
                    text = "\n".join(
                        c.get("text", "")
                        for c in content
                        if c.get("type") == "input_text"
                    )
                    messages.append({"role": "user", "content": text})
            else:
                messages.append({"role": "user", "content": str(content or "")})
            i += 1
            continue

        if role == "assistant":
            content_list = item.get("content", [])
            reasoning_content = str(item.get("reasoning_content", "") or "")
            if isinstance(content_list, list):
                text = "\n".join(
                    c.get("text", "")
                    for c in content_list
                    if c.get("type") == "output_text"
                )
            else:
                text = str(content_list or "")

            tool_calls: list[dict] = []
            j = i + 1
            while j < len(items) and items[j].get("type") == "function_call":
                fc = items[j]
                tool_calls.append(
                    {
                        "id": fc["call_id"],
                        "type": "function",
                        "function": {
                            "name": fc["name"],
                            "arguments": fc.get("arguments", "{}"),
                        },
                    }
                )
                j += 1

            if tool_calls:
                assistant_message = {
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": tool_calls,
                }
                if reasoning_content:
                    assistant_message["reasoning_content"] = reasoning_content
                messages.append(assistant_message)
                i = j
            else:
                assistant_message = {"role": "assistant", "content": text}
                if reasoning_content:
                    assistant_message["reasoning_content"] = reasoning_content
                messages.append(assistant_message)
                i += 1
            continue

        if itype == "function_call":
            tool_calls = []
            while i < len(items) and items[i].get("type") == "function_call":
                fc = items[i]
                tool_calls.append(
                    {
                        "id": fc["call_id"],
                        "type": "function",
                        "function": {
                            "name": fc["name"],
                            "arguments": fc.get("arguments", "{}"),
                        },
                    }
                )
                i += 1
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls,
                }
            )
            continue

        if itype == "function_call_output":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item["call_id"],
                    "content": str(item.get("output", "")),
                }
            )
            i += 1
            continue

        i += 1

    return messages


class LiteLLMClient:
    """Multi-provider LLM client backed by LiteLLM."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "gpt-4o",
        base_url: Optional[str] = None,
        provider_kwargs: Optional[dict[str, Any]] = None,
        env_overrides: Optional[dict[str, str]] = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._base_url = base_url
        self._provider_kwargs = dict(provider_kwargs or {})
        self._env_overrides = dict(env_overrides or {})
        self._configure_litellm()

    def _configure_litellm(self) -> None:
        try:
            import litellm
            import warnings

            litellm.drop_params = True
            litellm.suppress_debug_info = True
            warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
        except ImportError:
            pass

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
                exc_name = type(exc).__name__.lower()
                is_transient = any(
                    key in exc_name
                    for key in (
                        "ratelimit",
                        "connection",
                        "timeout",
                        "serviceunavailable",
                        "overloaded",
                        "apierror",
                    )
                )
                if is_transient and retry_count < max_retries:
                    retry_count += 1
                    delay = base_delay * (2 ** (retry_count - 1))
                    logger.warning(
                        "Transient error (attempt %d/%d), retrying in %.1fs: %s",
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
                else:
                    yield StreamErrorEvent(message=str(exc), retry_count=retry_count)
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
    ) -> AsyncIterator:
        try:
            import litellm
        except ImportError as exc:
            yield StreamErrorEvent(
                message="litellm is not installed. Run: pip install litellm",
                retry_count=0,
            )
            raise StopAsyncIteration from exc

        enable_caching = bool(extra_params.get("prompt_caching", False))
        messages = _to_chat_messages(
            instructions,
            input,
            model=self.model,
            enable_caching=enable_caching,
        )

        # Normalize flat Responses-API format → nested Chat-Completions format, then sanitize names
        normalized = _normalize_tools_to_chat_format(tools) if tools else tools
        safe_tools, tool_name_map = _sanitize_tools(normalized) if normalized else (normalized, {})
        messages = _patch_message_tool_names(messages, tool_name_map)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            **extra_params,
        }
        if safe_tools:
            kwargs["tools"] = safe_tools
            kwargs["tool_choice"] = "auto"
        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens
        if self._base_url:
            kwargs["base_url"] = self._base_url
        if self._api_key:
            kwargs["api_key"] = self._api_key
        kwargs.update(self._provider_kwargs)
        kwargs["stream_options"] = {"include_usage": True}

        tool_buffers: dict[int, dict[str, str]] = {}
        final_usage: Any = None
        reasoning_parts: list[str] = []

        async with _temporary_env(self._env_overrides):
            response = await litellm.acompletion(**kwargs)

            async for chunk in response:
                if not getattr(chunk, "choices", None):
                    usage = getattr(chunk, "usage", None)
                    if usage:
                        final_usage = usage
                    continue

                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue

                content = getattr(delta, "content", None)
                if content:
                    yield TextDeltaEvent(delta=content)

                thinking = getattr(delta, "thinking", None)
                if thinking:
                    reasoning_parts.append(str(thinking))
                    yield ReasoningDeltaEvent(delta=thinking)

                reasoning_content = getattr(delta, "reasoning_content", None)
                if reasoning_content:
                    reasoning_text = str(reasoning_content)
                    reasoning_parts.append(reasoning_text)
                    yield ReasoningDeltaEvent(delta=reasoning_text)

                tc_deltas = getattr(delta, "tool_calls", None)
                if tc_deltas:
                    for tc in tc_deltas:
                        idx = int(getattr(tc, "index", 0) or 0)
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

                usage = getattr(chunk, "usage", None)
                if usage and (
                    getattr(usage, "prompt_tokens", None)
                    or getattr(usage, "total_tokens", None)
                ):
                    final_usage = usage

        for idx in sorted(tool_buffers):
            buf = tool_buffers[idx]
            raw_args = buf["args"]
            try:
                parsed: dict[str, Any] = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                logger.warning(
                    "Failed to parse tool args for %r: %r",
                    buf["name"],
                    raw_args,
                )
                parsed = {"_raw": raw_args}
            # Restore original name if it was sanitized
            original_name = tool_name_map.get(buf["name"], buf["name"])
            yield ToolCallEvent(
                id=buf["id"],
                name=original_name,
                input=parsed,
                reasoning_content="".join(reasoning_parts),
            )

        if final_usage is not None:
            yield CompletedEvent(
                input_tokens=int(getattr(final_usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(final_usage, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(final_usage, "total_tokens", 0) or 0),
            )
        else:
            yield CompletedEvent(input_tokens=0, output_tokens=0, total_tokens=0)

    async def list_models(self) -> list[str]:
        try:
            import litellm

            models = litellm.model_list or []
            return sorted(str(m) for m in models)
        except Exception:
            return []

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> "LiteLLMClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
