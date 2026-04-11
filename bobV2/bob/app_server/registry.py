from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from bob.config.loader import load_config
from bob.core.session import BobSession
from bob.protocol.items import ImageUserInput, TextUserInput
from bob.protocol.ops import InterruptOp, UserTurnOp


def _ts() -> int:
    return int(time.time() * 1000)


@dataclass
class TurnState:
    id: str
    submission_id: str
    thread_id: str
    state: str = "queued"
    created_at_ts: int = field(default_factory=_ts)
    updated_at_ts: int = field(default_factory=_ts)
    turn_id: Optional[str] = None
    output_text: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "submission_id": self.submission_id,
            "thread_id": self.thread_id,
            "state": self.state,
            "created_at_ts": self.created_at_ts,
            "updated_at_ts": self.updated_at_ts,
            "turn_id": self.turn_id,
            "output_text": self.output_text,
            "error": self.error,
        }


@dataclass
class CommandState:
    id: str
    thread_id: str
    command: str
    submission_id: str
    state: str = "running"
    created_at_ts: int = field(default_factory=_ts)
    updated_at_ts: int = field(default_factory=_ts)
    exit_code: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "command": self.command,
            "submission_id": self.submission_id,
            "state": self.state,
            "created_at_ts": self.created_at_ts,
            "updated_at_ts": self.updated_at_ts,
            "exit_code": self.exit_code,
        }


@dataclass
class ThreadState:
    id: str
    session: BobSession
    created_at_ts: int
    updated_at_ts: int
    model: str
    cwd: str
    name: Optional[str] = None
    status: str = "running"
    turns: dict[str, TurnState] = field(default_factory=dict)
    turns_by_submission_id: dict[str, str] = field(default_factory=dict)
    commands: dict[str, CommandState] = field(default_factory=dict)
    closed_reason: Optional[str] = None
    events_task: Optional[asyncio.Task] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "model": self.model,
            "cwd": self.cwd,
            "name": self.name,
            "created_at_ts": self.created_at_ts,
            "updated_at_ts": self.updated_at_ts,
        }


class SessionRegistry:
    def __init__(self, event_bus: Any):
        self._threads: dict[str, ThreadState] = {}
        self._event_bus = event_bus
        self._lock = asyncio.Lock()

    async def create_thread(
        self,
        *,
        cwd: Optional[str],
        model: Optional[str],
        name: Optional[str],
        ephemeral: bool,
    ) -> ThreadState:
        use_cwd = Path(cwd).resolve() if cwd else Path.cwd()
        overrides: dict[str, Any] = {}
        if model:
            overrides["model"] = model
        config = load_config(cwd=use_cwd, cli_overrides=overrides)
        session = BobSession(config=config, cwd=use_cwd, ephemeral=ephemeral)
        await session.start()
        if name:
            await session.submit_set_name(name)

        thread_id = session.session_id
        now = _ts()
        state = ThreadState(
            id=thread_id,
            session=session,
            created_at_ts=now,
            updated_at_ts=now,
            model=config.model,
            cwd=str(use_cwd),
            name=name,
        )
        state.events_task = asyncio.create_task(self._consume_events(state))
        async with self._lock:
            self._threads[thread_id] = state
        return state

    async def get_thread(self, thread_id: str) -> Optional[ThreadState]:
        async with self._lock:
            return self._threads.get(thread_id)

    async def list_threads(self) -> list[ThreadState]:
        async with self._lock:
            return sorted(self._threads.values(), key=lambda t: t.created_at_ts, reverse=True)

    async def submit_turn(
        self,
        thread_id: str,
        items: list[dict[str, Any]],
        developer_message_override: Optional[str],
    ) -> TurnState:
        thread = await self.get_thread_or_raise(thread_id)
        user_items = []
        for it in items:
            t = str(it.get("type", ""))
            if t == "text":
                user_items.append(TextUserInput(type="text", text=str(it.get("text", ""))))
            elif t == "image":
                user_items.append(ImageUserInput(type="image", path=Path(str(it.get("path", "")))))
            else:
                user_items.append(TextUserInput(type="text", text=str(it)))

        op = UserTurnOp(items=user_items, developer_message_override=developer_message_override)
        submission_id = await thread.session.submit(op)
        turn_id = str(uuid.uuid4())
        now = _ts()
        turn = TurnState(
            id=turn_id,
            submission_id=submission_id,
            thread_id=thread_id,
            state="queued",
            created_at_ts=now,
            updated_at_ts=now,
        )
        thread.turns[turn_id] = turn
        thread.turns_by_submission_id[submission_id] = turn_id
        thread.updated_at_ts = now
        return turn

    async def list_turns(self, thread_id: str, limit: int = 50) -> list[TurnState]:
        thread = await self.get_thread_or_raise(thread_id)
        turns = sorted(thread.turns.values(), key=lambda t: t.created_at_ts, reverse=True)
        return turns[: max(1, min(limit, 500))]

    async def get_turn(self, thread_id: str, turn_id: str) -> Optional[TurnState]:
        thread = await self.get_thread_or_raise(thread_id)
        return thread.turns.get(turn_id)

    async def interrupt_turn(self, thread_id: str, graceful: bool = True) -> None:
        thread = await self.get_thread_or_raise(thread_id)
        await thread.session.submit(InterruptOp(type="interrupt", graceful=graceful))

    async def history(self, thread_id: str, limit: int = 200) -> list[dict[str, Any]]:
        thread = await self.get_thread_or_raise(thread_id)
        items = thread.session.context_manager.raw_items()
        return items[-max(1, min(limit, 2000)) :]

    async def close_thread(self, thread_id: str, reason: str = "closed") -> bool:
        thread = await self.get_thread(thread_id)
        if not thread:
            return False
        if thread.status == "closed":
            return True
        thread.status = "closed"
        thread.closed_reason = reason
        thread.updated_at_ts = _ts()
        await thread.session.shutdown()
        if thread.events_task:
            thread.events_task.cancel()
            try:
                await thread.events_task
            except (asyncio.CancelledError, Exception):
                pass
        return True

    async def shutdown_all(self) -> None:
        for thread_id in [t.id for t in await self.list_threads()]:
            await self.close_thread(thread_id, reason="server_shutdown")

    async def get_thread_or_raise(self, thread_id: str) -> ThreadState:
        thread = await self.get_thread(thread_id)
        if thread is None:
            from bob.app_server.errors import not_found

            raise not_found("Thread not found", thread_id=thread_id)
        return thread

    async def _consume_events(self, thread: ThreadState) -> None:
        try:
            async for event in thread.session.events():
                payload = {
                    "thread_id": thread.id,
                    "submission_id": event.id,
                    "event": event.msg.model_dump(),
                }
                channels = [f"thread:{thread.id}"]

                turn_id = thread.turns_by_submission_id.get(event.id)
                if turn_id:
                    channels.append(f"turn:{turn_id}")
                    turn = thread.turns.get(turn_id)
                else:
                    turn = None

                msg_type = payload["event"].get("type", "")
                now = _ts()
                if turn:
                    if msg_type == "turn_started":
                        turn.state = "running"
                        turn.turn_id = payload["event"].get("turn_id")
                    elif msg_type == "text_delta":
                        turn.output_text += payload["event"].get("delta", "")
                    elif msg_type == "text_final":
                        turn.output_text = payload["event"].get("text", turn.output_text)
                    elif msg_type == "error":
                        turn.state = "failed"
                        turn.error = payload["event"].get("message", "Unknown error")
                    elif msg_type == "turn_ended":
                        turn.state = "completed"
                    elif msg_type == "turn_interrupted":
                        turn.state = "interrupted"
                    turn.updated_at_ts = now
                    thread.updated_at_ts = now

                if msg_type == "session_ended":
                    thread.status = "closed"
                    thread.updated_at_ts = now

                await self._event_bus.publish(channels, payload)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            await self._event_bus.publish(
                [f"thread:{thread.id}"],
                {"thread_id": thread.id, "event": {"type": "error", "message": str(exc)}},
            )

