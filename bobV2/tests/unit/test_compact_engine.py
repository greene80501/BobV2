from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bob.core.compact import run_compact
from bob.core.context_manager import ContextManager
from bob.llm.client import StreamErrorEvent, TextDeltaEvent


class _FakeClient:
    def __init__(self, batches):
        self._batches = list(batches)
        self.calls = []

    async def stream_turn(self, **kwargs):
        self.calls.append(kwargs)
        events = self._batches.pop(0) if self._batches else []
        for ev in events:
            yield ev


def _make_session(client, items):
    cm = ContextManager()
    cm.record_items(items)
    return SimpleNamespace(
        client=client,
        context_manager=cm,
        config=SimpleNamespace(compact_max_retries=2),
    )


def test_run_compact_returns_structured_result() -> None:
    client = _FakeClient([[TextDeltaEvent(delta="Summary text")]])
    session = _make_session(
        client,
        [{"role": "user", "content": [{"type": "input_text", "text": "hello world"}]}],
    )
    result = asyncio.run(run_compact(session, reason="manual"))
    assert result is not None
    assert result.reason == "manual"
    assert result.summary_text.startswith("Context compaction summary:")
    assert len(result.new_history) >= 1


def test_run_compact_retries_on_prompt_too_long() -> None:
    client = _FakeClient([
        [StreamErrorEvent(message="Prompt too long for context window", retry_count=0)],
        [TextDeltaEvent(delta="Recovered summary")],
    ])
    session = _make_session(
        client,
        [
            {"role": "user", "content": [{"type": "input_text", "text": "u1"}]},
            {"role": "assistant", "content": [{"type": "output_text", "text": "a1"}]},
            {"role": "user", "content": [{"type": "input_text", "text": "u2"}]},
        ],
    )
    result = asyncio.run(run_compact(session, reason="context_window_exceeded"))
    assert result is not None
    assert result.reason == "context_window_exceeded"
    assert len(client.calls) == 2

