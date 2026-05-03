from __future__ import annotations

import asyncio
import time as _time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bob.core.session import BobSession
    from bob.core.agents.registry import AgentRecord

from bob.core.agents.mailbox import Mailbox
from bob.core.agents.registry import AgentStatus


class BobSubAgent:
    """
    Background sub-agent backed by its own BobSession.

    Progress events are forwarded to the parent session for UI display. When the
    agent uses an isolated git worktree, successful completion auto-merges the
    result back into the main working tree via a local squash merge.
    """

    def __init__(
        self,
        record: "AgentRecord",
        session: "BobSession",
        parent_session: "BobSession",
        completion_queue: asyncio.Queue,
        worktree_manager=None,
        run_store=None,
    ) -> None:
        self.agent_id = record.agent_id
        self.path = record.path
        self.task = record.task
        self._record = record
        self._session = session
        self._parent = parent_session
        self._completion_queue = completion_queue
        self._worktree_manager = worktree_manager
        self._run_store = run_store
        self.mailbox = Mailbox()
        self._asyncio_task: Optional[asyncio.Task] = None

    def start(self) -> asyncio.Task:
        self._asyncio_task = asyncio.create_task(
            self.run(),
            name=f"bob-agent-{self.agent_id}",
        )
        return self._asyncio_task

    def cancel(self) -> None:
        if self._asyncio_task and not self._asyncio_task.done():
            self._asyncio_task.cancel()

    async def run(self) -> None:
        from bob.protocol.items import TextUserInput as UserInput
        from bob.protocol.ops import UserTurnOp
        from bob.protocol.config_types import HookEventName, ReviewDecision
        from bob.protocol.ops import (
            ExecApprovalOp,
            NetworkApprovalOp,
            PatchApprovalOp,
            UserInputAnswerOp,
        )

        try:
            await self._session.start()
            await self._set_status(AgentStatus.RUNNING)
            await self._emit_spawned()

            asyncio.create_task(self._parent.hook_runner.run_hooks(
                HookEventName.SUBAGENT_START,
                {"agent_id": self.agent_id, "task": self.task[:200]},
            ))

            initial_text = self.task
            if self._session.context_manager.size > 0:
                initial_text = (
                    "You are a sub-agent. The prior history is background context only.\n\n"
                    f"Your task: {self.task}"
                )

            await self._session.submit(UserTurnOp(
                type="user_turn",
                items=[UserInput(type="text", text=initial_text)],
            ))

            final_text = ""
            async for event in self._session.events():
                msg_type = getattr(event.msg, "type", "")

                if msg_type == "session_ended":
                    break
                if msg_type == "text_final":
                    final_text = event.msg.text
                    continue
                if msg_type == "token_budget":
                    self._record.progress.token_count = getattr(event.msg, "used_tokens", 0)
                    continue
                if msg_type == "tool_call_started":
                    tname = getattr(event.msg, "tool_name", "")
                    tinput = getattr(event.msg, "tool_input", {})
                    detail = ""
                    for key in ("path", "file_path", "command", "query", "url", "pattern"):
                        value = tinput.get(key, "")
                        if value:
                            detail = str(value)[:60]
                            break
                    self._record.progress.record_tool(tname, detail)
                    self._persist()
                    await self._emit_progress()
                    continue
                if msg_type == "network_approval_requested":
                    await self._session.submit(NetworkApprovalOp(
                        url=getattr(event.msg, "url", ""),
                        domain=getattr(event.msg, "domain", ""),
                        approved=True,
                        approve_always=True,
                        request_id=getattr(event.msg, "request_id", ""),
                    ))
                    continue
                if msg_type == "exec_approval_requested":
                    await self._session.submit(ExecApprovalOp(
                        tool_call_id=getattr(event.msg, "tool_call_id", ""),
                        decision=ReviewDecision.APPROVED,
                    ))
                    continue
                if msg_type == "patch_approval_requested":
                    await self._session.submit(PatchApprovalOp(
                        tool_call_id=getattr(event.msg, "tool_call_id", ""),
                        decision=ReviewDecision.APPROVED,
                    ))
                    continue
                if msg_type == "user_input_request":
                    await self._session.submit(UserInputAnswerOp(
                        request_id=getattr(event.msg, "request_id", ""),
                        answer="(sub-agent: no user available)",
                    ))
                    continue
                if msg_type == "turn_ended":
                    pending = self.mailbox.drain()
                    trigger_msgs = [message for message in pending if message.trigger_turn]
                    if trigger_msgs:
                        combined = "\n\n".join(message.content for message in trigger_msgs)
                        await self._session.submit(UserTurnOp(
                            type="user_turn",
                            items=[UserInput(type="text", text=combined)],
                        ))
                    else:
                        await self._session.shutdown()

            result = final_text or "Task completed."
            if self._worktree_manager is not None:
                merge_ok, merge_msg = self._worktree_manager.merge_and_cleanup(self.agent_id)
                self._record.merge_success = merge_ok
                self._record.merge_status = merge_msg
                if merge_msg and merge_msg != "no worktree":
                    result = f"{result}\n\n[merge] {merge_msg}"

            await self._set_status(AgentStatus.COMPLETED, result=result)
            await self._emit_completed("completed", result=result)
            asyncio.create_task(self._parent.hook_runner.run_hooks(
                HookEventName.SUBAGENT_STOP,
                {"agent_id": self.agent_id, "status": "completed"},
            ))

        except asyncio.CancelledError:
            if self._worktree_manager is not None:
                self._worktree_manager.cleanup_no_merge(self.agent_id)
            await self._set_status(AgentStatus.INTERRUPTED)
            await self._emit_completed("interrupted")
            asyncio.create_task(self._parent.hook_runner.run_hooks(
                HookEventName.SUBAGENT_STOP,
                {"agent_id": self.agent_id, "status": "interrupted"},
            ))
            raise

        except Exception as exc:
            if self._worktree_manager is not None:
                self._worktree_manager.cleanup_no_merge(self.agent_id)
            err = str(exc)
            await self._set_status(AgentStatus.ERRORED, error=err)
            await self._emit_completed("errored", error=err)
            asyncio.create_task(self._parent.hook_runner.run_hooks(
                HookEventName.SUBAGENT_STOP,
                {"agent_id": self.agent_id, "status": "errored", "error": err},
            ))

        finally:
            try:
                await self._session.shutdown()
            except Exception:
                pass
            try:
                self._completion_queue.put_nowait(self.agent_id)
            except asyncio.QueueFull:
                pass

    async def _set_status(
        self,
        status: AgentStatus,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        self._record.status = status
        if status == AgentStatus.RUNNING and self._record.started_at == 0.0:
            self._record.started_at = _time.time()
        if result is not None:
            self._record.result = result
        if error is not None:
            self._record.error = error
        if status.is_terminal:
            self._record._done_event.set()
        self._persist()

    def _persist(self) -> None:
        if self._run_store is not None:
            self._run_store.upsert_record(self._parent.session_id, self._record)

    async def _emit_to_parent(self, msg_obj) -> None:
        from bob.protocol.events import Event

        try:
            self._parent._eq.put_nowait(Event(id=f"agent-{self.agent_id}", msg=msg_obj))
        except (asyncio.QueueFull, Exception):
            pass

    async def _emit_spawned(self) -> None:
        from bob.protocol.events import AgentSpawnedEvent

        await self._emit_to_parent(AgentSpawnedEvent(
            agent_id=self.agent_id,
            path=str(self.path),
            name=self.path.name,
            task=self.task[:120],
        ))

    async def _emit_progress(self) -> None:
        from bob.protocol.events import AgentProgressEvent

        progress = self._record.progress
        await self._emit_to_parent(AgentProgressEvent(
            agent_id=self.agent_id,
            path=str(self.path),
            name=self.path.name,
            status=self._record.status.value,
            last_activity=progress.last_activity,
            tool_use_count=progress.tool_use_count,
            token_count=progress.token_count,
        ))

    async def _emit_completed(
        self,
        status: str,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        from bob.protocol.events import AgentCompletedEvent

        progress = self._record.progress
        await self._emit_to_parent(AgentCompletedEvent(
            agent_id=self.agent_id,
            path=str(self.path),
            name=self.path.name,
            status=status,
            result=(result or "")[:500] if result else None,
            error=error,
            tool_use_count=progress.tool_use_count,
            token_count=progress.token_count,
        ))
