from __future__ import annotations

from types import SimpleNamespace

from bob.llm.client import (
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


def test_to_chat_messages_preserves_tool_call_provider_specific_fields() -> None:
    items = [
        {
            "role": "assistant",
            "content": [],
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "spawn_agent",
            "arguments": "{\"task\":\"inspect\"}",
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
                        "name": "spawn_agent",
                        "arguments": "{\"task\":\"inspect\"}",
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
