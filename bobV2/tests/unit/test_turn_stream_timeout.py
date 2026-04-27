from __future__ import annotations

import asyncio

import pytest

from bob.core.turn import _next_stream_event


class _NeverYield:
    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(1)
        raise StopAsyncIteration


class _OneShot:
    def __init__(self) -> None:
        self._done = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._done:
            raise StopAsyncIteration
        self._done = True
        return "delta"


@pytest.mark.asyncio
async def test_next_stream_event_times_out_with_provider_stall_message() -> None:
    stream = _NeverYield().__aiter__()

    with pytest.raises(TimeoutError, match="Provider stream stalled after 0s"):
        await _next_stream_event(
            stream,
            idle_timeout_seconds=0.01,
            model="kimi/kimi-for-coding",
        )


@pytest.mark.asyncio
async def test_next_stream_event_returns_value_when_stream_progresses() -> None:
    stream = _OneShot().__aiter__()

    event = await _next_stream_event(
        stream,
        idle_timeout_seconds=0.5,
        model="kimi/kimi-for-coding",
    )

    assert event == "delta"
