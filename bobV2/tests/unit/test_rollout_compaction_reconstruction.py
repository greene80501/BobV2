from __future__ import annotations

from bob.core.rollout_reconstruction import reconstruct_history


def test_reconstruct_history_uses_latest_compacted_checkpoint():
    rollout = [
        {"type": "session_meta", "session_id": "s1"},
        {"type": "response_item", "item": {"role": "user", "content": [{"type": "input_text", "text": "u1"}]}},
        {"type": "response_item", "item": {"role": "assistant", "content": [{"type": "output_text", "text": "a1"}]}},
        {
            "type": "compacted",
            "replacement_history": [
                {"role": "user", "content": [{"type": "input_text", "text": "checkpoint"}]},
            ],
        },
        {"type": "response_item", "item": {"role": "assistant", "content": [{"type": "output_text", "text": "after"}]}},
    ]

    result = reconstruct_history(rollout)
    assert len(result.history) == 2
    assert result.history[0]["content"][0]["text"] == "checkpoint"
    assert result.history[1]["content"][0]["text"] == "after"


def test_reconstruct_history_applies_thread_rollback():
    rollout = [
        {"type": "session_meta", "session_id": "s1"},
        {"type": "response_item", "item": {"role": "user", "content": [{"type": "input_text", "text": "u1"}]}},
        {"type": "response_item", "item": {"role": "assistant", "content": [{"type": "output_text", "text": "a1"}]}},
        {"type": "response_item", "item": {"role": "user", "content": [{"type": "input_text", "text": "u2"}]}},
        {"type": "response_item", "item": {"role": "assistant", "content": [{"type": "output_text", "text": "a2"}]}},
        {"type": "thread_rolled_back", "num_turns": 1},
    ]

    result = reconstruct_history(rollout)
    assert len(result.history) == 2
    assert result.history[0]["content"][0]["text"] == "u1"
    assert result.history[1]["content"][0]["text"] == "a1"

