"""LiteLLM-based multi-provider async streaming client for Bob.

Drop-in replacement for bob.client.openai_client.BobClient.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import json
import logging
import os
import re
import threading
from typing import Any, AsyncIterator, Optional, Union

logger = logging.getLogger(__name__)
_ENV_OVERRIDE_LOCK: threading.Lock | None = None
_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 45.0

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


def _merge_provider_specific_fields(*sources: Any) -> Optional[dict[str, Any]]:
    merged: dict[str, Any] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if value is not None and key not in merged:
                merged[key] = value
    return merged or None


def _history_function_call_to_chat_tool_call(fc: dict[str, Any]) -> dict[str, Any]:
    tool_call = {
        "id": fc["call_id"],
        "type": "function",
        "function": {
            "name": fc["name"],
            "arguments": fc.get("arguments", "{}"),
        },
    }
    provider_specific_fields = _merge_provider_specific_fields(
        fc.get("provider_specific_fields")
    )
    if provider_specific_fields:
        tool_call["provider_specific_fields"] = provider_specific_fields
    return tool_call


def _extract_tool_call_provider_specific_fields(tc: Any, fn: Any = None) -> Optional[dict[str, Any]]:
    return _merge_provider_specific_fields(
        getattr(tc, "provider_specific_fields", None),
        getattr(fn, "provider_specific_fields", None),
    )


@dataclass
class TextDeltaEvent:
    delta: str


@dataclass
class ToolCallEvent:
    id: str
    name: str
    input: dict[str, Any]
    reasoning_content: str = ""
    provider_specific_fields: Optional[dict[str, Any]] = None


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


def _get_env_override_lock() -> threading.Lock:
    global _ENV_OVERRIDE_LOCK
    if _ENV_OVERRIDE_LOCK is None:
        _ENV_OVERRIDE_LOCK = threading.Lock()
    return _ENV_OVERRIDE_LOCK


@contextmanager
def _temporary_env(overrides: dict[str, str]):
    if not overrides:
        yield
        return

    lock = _get_env_override_lock()
    with lock:
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


def _provider_timeout_seconds(extra_params: dict[str, Any]) -> float:
    for key in ("timeout", "request_timeout"):
        raw = extra_params.get(key)
        if raw is None:
            continue
        try:
            return max(0.1, min(float(raw), 900.0))
        except (TypeError, ValueError):
            continue
    return _DEFAULT_PROVIDER_TIMEOUT_SECONDS


def _emit_threadsafe(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue, kind: str, payload: Any) -> None:
    try:
        loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))
    except RuntimeError:
        # The consumer loop may already be closed after a timeout/failure.
        return


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
                tool_calls.append(_history_function_call_to_chat_tool_call(fc))
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
                tool_calls.append(_history_function_call_to_chat_tool_call(fc))
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
                exc_text = str(exc).lower()
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
                if "provider stream stalled after" in exc_text:
                    is_transient = False
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
        provider_timeout_seconds = _provider_timeout_seconds(kwargs)
        kwargs.setdefault("timeout", provider_timeout_seconds)

        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        stop_event = threading.Event()

        def _worker() -> None:
            asyncio.run(
                self._stream_once_worker(
                    kwargs=kwargs,
                    tool_name_map=tool_name_map,
                    queue=queue,
                    loop=loop,
                    stop_event=stop_event,
                    provider_timeout_seconds=provider_timeout_seconds,
                )
            )

        thread = threading.Thread(
            target=_worker,
            name=f"bob-litellm-{self.model.replace('/', '-')}",
            daemon=True,
        )
        thread.start()

        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(
                        queue.get(),
                        timeout=provider_timeout_seconds,
                    )
                except asyncio.TimeoutError as exc:
                    stop_event.set()
                    raise TimeoutError(
                        f"Provider stream stalled after {int(provider_timeout_seconds)}s with no progress "
                        f"from model '{self.model}'."
                    ) from exc

                if kind == "event":
                    yield payload
                    continue
                if kind == "error":
                    raise payload
                if kind == "done":
                    break
        finally:
            stop_event.set()

    async def _stream_once_worker(
        self,
        *,
        kwargs: dict[str, Any],
        tool_name_map: dict[str, str],
        queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        stop_event: threading.Event,
        provider_timeout_seconds: float,
    ) -> None:
        try:
            import litellm
        except ImportError:
            _emit_threadsafe(
                loop,
                queue,
                "event",
                StreamErrorEvent(
                    message="litellm is not installed. Run: pip install litellm",
                    retry_count=0,
                ),
            )
            _emit_threadsafe(loop, queue, "done", None)
            return

        tool_buffers: dict[int, dict[str, Any]] = {}
        final_usage: Any = None
        reasoning_parts: list[str] = []

        try:
            with _temporary_env(self._env_overrides):
                response = await asyncio.wait_for(
                    litellm.acompletion(**kwargs),
                    timeout=provider_timeout_seconds + 5.0,
                )

                async for chunk in response:
                    if stop_event.is_set():
                        return
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
                        _emit_threadsafe(loop, queue, "event", TextDeltaEvent(delta=content))

                    thinking = getattr(delta, "thinking", None)
                    if thinking:
                        reasoning_parts.append(str(thinking))
                        _emit_threadsafe(loop, queue, "event", ReasoningDeltaEvent(delta=thinking))

                    reasoning_content = getattr(delta, "reasoning_content", None)
                    if reasoning_content:
                        reasoning_text = str(reasoning_content)
                        reasoning_parts.append(reasoning_text)
                        _emit_threadsafe(
                            loop,
                            queue,
                            "event",
                            ReasoningDeltaEvent(delta=reasoning_text),
                        )

                    tc_deltas = getattr(delta, "tool_calls", None)
                    if tc_deltas:
                        for tc in tc_deltas:
                            idx = int(getattr(tc, "index", 0) or 0)
                            fn = getattr(tc, "function", None)
                            fn_name = getattr(fn, "name", None) if fn else None
                            fn_args = getattr(fn, "arguments", None) if fn else None
                            tc_id = getattr(tc, "id", None)

                            if fn_name and idx in tool_buffers and tool_buffers[idx]["name"]:
                                idx = max(tool_buffers.keys()) + 1

                            if idx not in tool_buffers:
                                tool_buffers[idx] = {"id": "", "name": "", "args": ""}
                            buf = tool_buffers[idx]
                            if tc_id:
                                buf["id"] = tc_id
                            if fn_name:
                                buf["name"] += fn_name
                            if fn_args:
                                buf["args"] += fn_args
                            provider_specific_fields = _extract_tool_call_provider_specific_fields(tc, fn)
                            if provider_specific_fields:
                                buf["provider_specific_fields"] = _merge_provider_specific_fields(
                                    buf.get("provider_specific_fields"),
                                    provider_specific_fields,
                                )

                    usage = getattr(chunk, "usage", None)
                    if usage and (
                        getattr(usage, "prompt_tokens", None)
                        or getattr(usage, "total_tokens", None)
                    ):
                        final_usage = usage

            for idx in sorted(tool_buffers):
                if stop_event.is_set():
                    return
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
                original_name = tool_name_map.get(buf["name"], buf["name"])
                _emit_threadsafe(
                    loop,
                    queue,
                    "event",
                    ToolCallEvent(
                        id=buf["id"],
                        name=original_name,
                        input=parsed,
                        reasoning_content="".join(reasoning_parts),
                        provider_specific_fields=buf.get("provider_specific_fields"),
                    ),
                )

            completed = (
                CompletedEvent(
                    input_tokens=int(getattr(final_usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(final_usage, "completion_tokens", 0) or 0),
                    total_tokens=int(getattr(final_usage, "total_tokens", 0) or 0),
                )
                if final_usage is not None
                else CompletedEvent(input_tokens=0, output_tokens=0, total_tokens=0)
            )
            _emit_threadsafe(loop, queue, "event", completed)
        except Exception as exc:
            _emit_threadsafe(loop, queue, "error", exc)
        finally:
            _emit_threadsafe(loop, queue, "done", None)

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
