from __future__ import annotations

from bob.core.context_manager import ContextManager


def test_trim_oldest_tool_results_keeps_recent() -> None:
    cm = ContextManager()
    cm.record_items([
        {"type": "function_call_output", "call_id": "1", "output": "o1"},
        {"type": "function_call_output", "call_id": "2", "output": "o2"},
        {"type": "function_call_output", "call_id": "3", "output": "o3"},
    ])
    removed = cm.trim_oldest_tool_results(keep_recent=1)
    assert removed == 2
    assert cm.raw_items()[0]["call_id"] == "3"


def test_trim_oldest_assistant_messages_keeps_recent() -> None:
    cm = ContextManager()
    cm.record_items([
        {"role": "assistant", "content": [{"type": "output_text", "text": "a1"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "a2"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "a3"}]},
    ])
    removed = cm.trim_oldest_assistant_messages(keep_recent=2)
    assert removed == 1
    assert len(cm.raw_items()) == 2

