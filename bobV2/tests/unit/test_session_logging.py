from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bob.core.session import BobSession
from bob.protocol.events import Event, InfoEvent
from bob.protocol.items import TextUserInput
from bob.protocol.ops import UserTurnOp


def _make_logging_session(tmp_path: Path) -> BobSession:
    session = BobSession.__new__(BobSession)
    session._sq = asyncio.Queue()
    session._eq = asyncio.Queue()
    session._recorder = None
    session._action_log_path = tmp_path / "actions.log"
    session._action_log_handle = session._action_log_path.open("a", encoding="utf-8", buffering=1)
    return session


@pytest.mark.asyncio
async def test_submit_logs_operations(tmp_path: Path) -> None:
    session = _make_logging_session(tmp_path)
    try:
        await session.submit(UserTurnOp(items=[TextUserInput(type="text", text="hello")]))
        text = session._action_log_path.read_text(encoding="utf-8")
        assert "[submit]" in text
        assert "type=user_turn" in text
        assert "\"text\": \"hello\"" in text
    finally:
        session._action_log_handle.close()


@pytest.mark.asyncio
async def test_emit_logs_events(tmp_path: Path) -> None:
    session = _make_logging_session(tmp_path)
    try:
        await session._emit(Event(id="evt-1", msg=InfoEvent(type="info", message="hello")))
        text = session._action_log_path.read_text(encoding="utf-8")
        assert "[event] id=evt-1 type=info" in text
        assert "\"message\": \"hello\"" in text
    finally:
        session._action_log_handle.close()
