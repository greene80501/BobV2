from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import pytest

from bob.llm.client import (
    CompletedEvent,
    LiteLLMClient,
    StreamErrorEvent,
    TextDeltaEvent,
    _extract_tool_call_provider_specific_fields,
    _to_chat_messages,
)


def test_to_chat_messages_preserves_reasoning_content_for_assistant_tool_calls() -> None:
    items = [
        {
            "role": "assistant",
            "content": [],
            "reasoning_content": "Need to inspect the repo first.",
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "list_dir",
            "arguments": "{\"path\":\".\"}",
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "README.md",
        },
    ]

    messages = _to_chat_messages("system prompt", items, model="openai/kimi-for-coding")

    assert messages[0] == {"role": "system", "content": "system prompt"}
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] is None
    assert messages[1]["reasoning_content"] == "Need to inspect the repo first."
    assert messages[1]["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "list_dir",
                "arguments": "{\"path\":\".\"}",
            },
        }
    ]
    assert messages[2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "README.md",
    }


def test_to_chat_messages_preserves_reasoning_content_for_plain_assistant_messages() -> None:
    items = [
        {
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Done."}],
            "reasoning_content": "Short private reasoning.",
        }
    ]

    messages = _to_chat_messages("", items, model="openai/kimi-for-coding")

    assert messages == [
        {
            "role": "assistant",
            "content": "Done.",
            "reasoning_content": "Short private reasoning.",
        }
    ]


def test_to_chat_messages_maps_medium_image_detail_to_provider_auto() -> None:
    items = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": "data:image/jpeg;base64,abc",
                    "detail": "medium",
                }
            ],
        }
    ]

    messages = _to_chat_messages("", items, model="openai/gpt-4o")

    assert messages == [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64,abc", "detail": "auto"},
                }
            ],
        }
    ]


def test_to_chat_messages_preserves_tool_call_provider_specific_fields() -> None:
    items = [
        {
            "role": "assistant",
            "content": [],
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": "{\"path\":\"README.md\"}",
            "provider_specific_fields": {"thought_signature": "sig-123"},
        },
    ]

    messages = _to_chat_messages("", items, model="vertex_ai/gemini-3-flash-preview")

    assert messages == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": "{\"path\":\"README.md\"}",
                    },
                    "provider_specific_fields": {"thought_signature": "sig-123"},
                }
            ],
        }
    ]


def test_extract_tool_call_provider_specific_fields_merges_tool_and_function_levels() -> None:
    function = SimpleNamespace(provider_specific_fields={"other": "value"})
    tool_call = SimpleNamespace(
        provider_specific_fields={"thought_signature": "sig-123"},
        function=function,
    )

    provider_specific_fields = _extract_tool_call_provider_specific_fields(
        tool_call,
        function,
    )

    assert provider_specific_fields == {
        "thought_signature": "sig-123",
        "other": "value",
    }


class _AsyncChunkStream:
    def __init__(self, chunks) -> None:
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


@pytest.mark.asyncio
async def test_stream_turn_times_out_when_litellm_blocks_before_first_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, float] = {}

    async def _blocking_acompletion(**kwargs):
        captured["timeout"] = float(kwargs["timeout"])
        time.sleep(0.3)
        return _AsyncChunkStream([])

    fake_litellm = SimpleNamespace(
        acompletion=_blocking_acompletion,
        model_list=[],
        drop_params=False,
        suppress_debug_info=False,
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    client = LiteLLMClient(model="openai/test-model")
    events = [
        ev
        async for ev in client.stream_turn(
            input=[{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
            instructions="Be concise.",
            tools=[],
            max_retries=0,
            extra_params={"timeout": 0.1},
        )
    ]

    assert captured["timeout"] == pytest.approx(0.1)
    assert len(events) == 1
    assert isinstance(events[0], StreamErrorEvent)
    assert "Provider stream stalled after 0s with no progress" in events[0].message


@pytest.mark.asyncio
async def test_stream_turn_yields_text_and_completion_events_via_worker_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _ok_acompletion(**_kwargs):
        return _AsyncChunkStream(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="hello",
                                thinking=None,
                                reasoning_content=None,
                                tool_calls=None,
                            )
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(
                        prompt_tokens=3,
                        completion_tokens=5,
                        total_tokens=8,
                    ),
                ),
            ]
        )

    fake_litellm = SimpleNamespace(
        acompletion=_ok_acompletion,
        model_list=[],
        drop_params=False,
        suppress_debug_info=False,
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    client = LiteLLMClient(model="openai/test-model")
    events = [
        ev
        async for ev in client.stream_turn(
            input=[{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
            instructions="Be concise.",
            tools=[],
            max_retries=0,
            extra_params={"timeout": 0.2},
        )
    ]

    assert isinstance(events[0], TextDeltaEvent)
    assert events[0].delta == "hello"
    assert isinstance(events[-1], CompletedEvent)
    assert events[-1].total_tokens == 8
