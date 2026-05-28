from __future__ import annotations

import asyncio
import time as _time
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bob.core.session import BobSession
    from bob.core.agents.registry import AgentRecord

from bob.core.agents.registry import AgentStatus


@dataclass
class TaskRequest:
    prompt: str
    description: str
    future: asyncio.Future[str]


class BobSubAgent:
    """
    Resumable child-session task runner.

    Each subagent owns a persistent child BobSession and processes one queued
    task prompt at a time. The same child session can be resumed later with a
    new prompt while retaining prior child context.
    """

    def __init__(
        self,
        record: "AgentRecord",
        session: "BobSession",
        parent_session: "BobSession",
        worktree_manager=None,
        run_store=None,
    ) -> None:
        self.agent_id = record.agent_id
        self.path = record.path
        self._record = record
        self._session = session
        self._parent = parent_session
        self._worktree_manager = worktree_manager
        self._run_store = run_store
        self._asyncio_task: Optional[asyncio.Task] = None
        self._requests: asyncio.Queue[TaskRequest] = asyncio.Queue()
        self._spawn_emitted = False

    def start(self) -> asyncio.Task:
        self._asyncio_task = asyncio.create_task(
            self.run(),
            name=f"bob-agent-{self.agent_id}",
        )
        return self._asyncio_task

    def submit(self, prompt: str, *, description: str) -> asyncio.Future[str]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._requests.put_nowait(TaskRequest(prompt=prompt, description=description, future=future))
        return future

    def cancel(self) -> None:
        if self._asyncio_task and not self._asyncio_task.done():
            self._asyncio_task.cancel()

    async def run(self) -> None:
        from bob.protocol.config_types import HookEventName
        from bob.protocol.items import TextUserInput as UserInput
        from bob.protocol.ops import UserTurnOp

        try:
            await self._session.start()
            while True:
                request = await self._requests.get()
                result = await self._run_request(request, UserInput, UserTurnOp)
                if not request.future.done():
                    request.future.set_result(result)
                asyncio.create_task(self._parent.hook_runner.run_hooks(
                    HookEventName.SUBAGENT_STOP,
                    {"agent_id": self.agent_id, "status": self._record.status.value},
                ))
        except asyncio.CancelledError:
            if self._worktree_manager is not None:
                self._worktree_manager.cleanup_no_merge(self.agent_id)
            await self._set_status(AgentStatus.INTERRUPTED)
            await self._emit_completed("interrupted")
            raise
        except Exception as exc:
            if self._worktree_manager is not None:
                self._worktree_manager.cleanup_no_merge(self.agent_id)
            err = str(exc)
            await self._set_status(AgentStatus.ERRORED, error=err)
            await self._emit_completed("errored", error=err)
        finally:
            try:
                await self._session.shutdown()
            except Exception:
                pass

    async def _run_request(self, request: TaskRequest, UserInput, UserTurnOp) -> str:
        from bob.protocol.config_types import HookEventName, ReviewDecision
        from bob.protocol.ops import ExecApprovalOp, NetworkApprovalOp, PatchApprovalOp, UserInputAnswerOp

        self._record.title = request.description or self._record.title or self.path.name
        self._record.task = request.prompt
        self._record.run_count += 1
        await self._set_status(AgentStatus.RUNNING)

        if not self._spawn_emitted:
            await self._emit_spawned()
            self._spawn_emitted = True
        else:
            await self._emit_progress()

        asyncio.create_task(self._parent.hook_runner.run_hooks(
            HookEventName.SUBAGENT_START,
            {"agent_id": self.agent_id, "task": self._record.task[:200]},
        ))

        initial_text = request.prompt
        if self._session.context_manager.size > 0:
            initial_text = (
                "You are continuing an existing subagent session. Use the prior child-session "
                "history as context for this new task.\n\n"
                f"Your task: {request.prompt}"
            )

        self._append_transcript(f"user: {request.prompt}")
        await self._session.submit(UserTurnOp(
            type="user_turn",
            items=[UserInput(type="text", text=initial_text)],
        ))

        final_text = ""
        async for event in self._session.events():
            msg_type = getattr(event.msg, "type", "")

            if msg_type == "session_ended":
                break
            if msg_type == "text_delta":
                continue
            if msg_type == "text_final":
                final_text = event.msg.text
                self._append_transcript(f"assistant: {event.msg.text[:400]}")
                continue
            if msg_type == "reasoning_delta":
                self._append_transcript(f"reasoning: {getattr(event.msg, 'delta', '')[:200]}")
                continue
            if msg_type == "token_budget":
                self._record.progress.token_count = getattr(event.msg, "used_tokens", 0)
                self._persist()
                continue
            if msg_type == "tool_call_started":
                tname = getattr(event.msg, "tool_name", "")
                tinput = getattr(event.msg, "tool_input", {})
                detail = ""
                for key in ("path", "file_path", "command", "query", "url", "pattern", "description"):
                    value = tinput.get(key, "")
                    if value:
                        detail = str(value)[:80]
                        break
                self._record.progress.record_tool(tname, detail)
                self._append_transcript(f"tool: {tname} {detail}".strip())
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
                break

        result = final_text or "Task completed."
        if self._worktree_manager is not None:
            merge_ok, merge_msg = self._worktree_manager.merge_and_cleanup(self.agent_id)
            self._record.merge_success = merge_ok
            self._record.merge_status = merge_msg
            if merge_msg and merge_msg != "no worktree":
                result = f"{result}\n\n[merge] {merge_msg}"

        await self._set_status(AgentStatus.COMPLETED, result=result)
        await self._emit_completed("completed", result=result)
        return result

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
            self._record.completed_at = _time.time()
            self._record._done_event.set()
        else:
            self._record.completed_at = 0.0
            self._record._done_event = asyncio.Event()
        self._persist()

    def _append_transcript(self, line: str) -> None:
        clean = (line or "").strip()
        if not clean:
            return
        self._record.transcript_tail = (self._record.transcript_tail + [clean])[-24:]

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
            task=self._record.task[:120],
            title=self._record.title[:80],
            session_id=self._record.session_id,
            agent_type=self._record.agent_type,
            group_id=self._record.group_id,
            group_size=self._record.group_size,
            group_index=self._record.group_index,
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
            title=self._record.title[:80],
            session_id=self._record.session_id,
            agent_type=self._record.agent_type,
            group_id=self._record.group_id,
            group_size=self._record.group_size,
            group_index=self._record.group_index,
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
            title=self._record.title[:80],
            session_id=self._record.session_id,
            agent_type=self._record.agent_type,
            group_id=self._record.group_id,
            group_size=self._record.group_size,
            group_index=self._record.group_index,
        ))
