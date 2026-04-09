"""
ThreadManager - in-process multi-agent orchestration for Bob.

Each sub-agent is a full BobSession running in the same asyncio event loop.
Output is forwarded to the parent session as InfoEvents so the existing TUI
renders it without any protocol changes.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bob.core.session import BobSession

# ANSI color palette assigned round-robin to sub-agents
_COLOR_PALETTE = [
    "\033[36m",   # cyan
    "\033[32m",   # green
    "\033[33m",   # yellow
    "\033[35m",   # magenta
    "\033[34m",   # blue
    "\033[31m",   # red
    "\033[37m",   # white
    "\033[96m",   # bright cyan
]
_RST = "\033[0m"


async def _build_memory_snapshot(
    session: "BobSession",
    *,
    task: str,
    result: str,
    changed_files: list[str],
) -> str:
    """Generate a reusable memory snapshot from the sub-agent's final context."""
    context_items = session.context_manager.raw_items()[-12:]
    context_json = json.dumps(context_items, ensure_ascii=True, default=str)
    if len(context_json) > 12_000:
        context_json = context_json[:12_000] + "\n... [truncated]"

    changed = "\n".join(f"- {path}" for path in changed_files[:20]) if changed_files else "- none"
    result_excerpt = result.strip()
    if len(result_excerpt) > 6_000:
        result_excerpt = result_excerpt[:6_000] + "\n... [truncated]"

    prompt = (
        "Create a durable memory snapshot for a coding sub-agent.\n"
        "Summarize only facts that would help the next run of the same named agent.\n"
        "Use this exact markdown structure:\n"
        "## Key findings\n"
        "- ...\n"
        "## Important facts\n"
        "- ...\n"
        "## Files modified\n"
        "- ...\n"
        "Keep it concise and avoid filler.\n\n"
        f"Task:\n{task}\n\n"
        f"Changed files:\n{changed}\n\n"
        f"Final result:\n{result_excerpt}\n\n"
        f"Recent context items:\n{context_json}"
    )

    parts: list[str] = []
    try:
        async for ev in session.client.stream_turn(
            input=[{
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }],
            instructions=(
                "You distill a sub-agent's final context into a compact reusable memory snapshot. "
                "Preserve concrete findings, constraints, and edited files."
            ),
            tools=[],
            max_retries=1,
            temperature=0.2,
            max_output_tokens=400,
            extra_params={"prompt_caching": False},
        ):
            delta = getattr(ev, "delta", None)
            if delta:
                parts.append(delta)
    except Exception:
        parts = []

    snapshot = "".join(parts).strip()
    if snapshot:
        return snapshot

    fallback_lines = [
        "## Key findings",
        f"- Task: {task[:300]}",
        f"- Outcome: {(result.strip()[:500] or 'No final result recorded.')}",
        "## Important facts",
        f"- Session cwd: {session.cwd}",
        "## Files modified",
    ]
    if changed_files:
        fallback_lines.extend(f"- {path}" for path in changed_files[:20])
    else:
        fallback_lines.append("- none")
    return "\n".join(fallback_lines)


async def _save_memory_snapshot(
    session: "BobSession",
    parent_session_id: str,
    agent_name: str,
    task: str,
    result: str,
    changed_files: list[str],
) -> None:
    """Summarise *result* and persist it as a session-scoped memory snapshot."""
    try:
        from bob.core.agent_memory import save_snapshot
        summary = await _build_memory_snapshot(
            session,
            task=task,
            result=result,
            changed_files=changed_files,
        )
        save_snapshot(parent_session_id, agent_name, task, summary)
    except Exception:
        pass  # Memory snapshots are best-effort


@dataclass
class AgentRecord:
    id: str
    session: "BobSession"
    task: str
    status: str          # pending | running | completed | failed
    result: Optional[str]
    color: str
    task_ref: Optional[asyncio.Task]
    name: Optional[str] = None
    done_event: asyncio.Event = field(default_factory=asyncio.Event)


class ThreadManager:
    """Manages a pool of sub-agent BobSessions."""

    def __init__(self, parent_session: "BobSession") -> None:
        self.parent_session = parent_session
        self._agents: dict[str, AgentRecord] = {}
        self._color_index = 0

    async def spawn(
        self,
        task: str,
        model: Optional[str] = None,
        cwd: Optional[str] = None,
        template: Optional[str] = None,
        name: Optional[str] = None,
    ) -> str:
        """Spawn a sub-agent and return its ID."""
        from bob.core.agent_memory import load_snapshot
        from bob.core.agent_templates import get_template
        from bob.core.session import BobSession

        config = self.parent_session.config.model_copy(deep=True)
        if model:
            config = config.model_copy(update={"model": model})

        tmpl = get_template(template) if template else None
        agent_cwd: Path = Path(cwd) if cwd else self.parent_session.cwd

        session = BobSession(config=config, cwd=agent_cwd, ephemeral=True)
        await session.start()

        agent_id = str(uuid.uuid4())[:8]
        color = _COLOR_PALETTE[self._color_index % len(_COLOR_PALETTE)]
        self._color_index += 1

        record = AgentRecord(
            id=agent_id,
            session=session,
            task=task,
            status="pending",
            result=None,
            color=color,
            task_ref=None,
            name=name,
        )
        self._agents[agent_id] = record

        if tmpl and tmpl.allowed_tools:
            allowed = tmpl.allowed_tools
            all_names = list(session.tool_registry._tools.keys())
            for tname in all_names:
                if tname not in allowed:
                    session.tool_registry.unregister(tname)

        if tmpl and tmpl.system_prompt_suffix:
            session._system_prompt = (
                (session._system_prompt or "") + "\n\n" + tmpl.system_prompt_suffix
            )

        if name:
            prior = load_snapshot(self.parent_session.session_id, name)
            if prior:
                session._system_prompt = (
                    (session._system_prompt or "")
                    + f"\n\n## Memory from prior session\n{prior}"
                )

        task_obj = asyncio.create_task(self._agent_worker(agent_id, task))
        record.task_ref = task_obj
        record.status = "running"
        return agent_id

    async def send_message(self, agent_id: str, message: str) -> str:
        """Submit a new user message to a running sub-agent."""
        record = self._get(agent_id)
        from bob.protocol.items import TextUserInput
        from bob.protocol.ops import UserTurnOp
        await record.session.submit(
            UserTurnOp(items=[TextUserInput(type="text", text=message)])
        )
        return f"Message sent to agent {agent_id}"

    async def wait_for_agent(
        self, agent_id: str, timeout: Optional[float] = None
    ) -> Optional[str]:
        """Wait until the agent finishes and return its result text."""
        record = self._get(agent_id)
        try:
            await asyncio.wait_for(record.done_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return record.result

    async def close_agent(self, agent_id: str, reason: Optional[str] = None) -> None:
        """Cancel a sub-agent task and shut down its session."""
        record = self._get(agent_id)
        if record.task_ref and not record.task_ref.done():
            record.task_ref.cancel()
            try:
                await record.task_ref
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await record.session.shutdown()
        except Exception:
            pass
        record.status = "failed"
        record.done_event.set()

    def list_agents(self, include_completed: bool = False) -> list[dict]:
        """Return descriptors for all tracked agents."""
        result = []
        for rec in self._agents.values():
            if not include_completed and rec.status in ("completed", "failed"):
                continue
            result.append({
                "id": rec.id,
                "status": rec.status,
                "task": rec.task,
                "result_preview": (rec.result or "")[:80] if rec.result else None,
            })
        return result

    async def shutdown_all(self) -> None:
        """Close all agents - called on parent session shutdown."""
        for agent_id in list(self._agents.keys()):
            try:
                await self.close_agent(agent_id, reason="parent shutdown")
            except Exception:
                pass

    def _get(self, agent_id: str) -> AgentRecord:
        if agent_id not in self._agents:
            raise KeyError(f"No sub-agent with id '{agent_id}'")
        return self._agents[agent_id]

    async def _agent_worker(self, agent_id: str, task: str) -> None:
        """Drive the sub-agent: submit the task, drain events, forward output."""
        record = self._get(agent_id)
        session = record.session
        color = record.color
        short_id = agent_id[:6]

        def _fwd(text: str) -> None:
            """Emit a forwarded InfoEvent to the parent session."""
            from bob.protocol.events import Event, InfoEvent
            import asyncio as _as

            msg = InfoEvent(
                type="info",
                message=f"[{color}{short_id}{_RST}] {text}",
            )
            try:
                loop = _as.get_event_loop()
                loop.call_soon_threadsafe(
                    lambda: _as.ensure_future(
                        self.parent_session._emit(Event(id="subagent", msg=msg))
                    )
                )
            except Exception:
                pass

        try:
            from bob.protocol.events import (
                ErrorEvent,
                SessionEndedEvent,
                TextDeltaEvent,
                TurnEndedEvent,
                TurnInterruptedEvent,
            )
            from bob.protocol.items import TextUserInput
            from bob.protocol.ops import UserTurnOp

            await session.submit(
                UserTurnOp(items=[TextUserInput(type="text", text=task)])
            )

            text_buf: list[str] = []
            async for event in session.events():
                msg = event.msg
                if isinstance(msg, TextDeltaEvent):
                    text_buf.append(msg.delta)
                    _fwd(msg.delta)
                elif isinstance(msg, TurnEndedEvent):
                    record.result = "".join(text_buf)
                    record.status = "completed"
                    _fwd(f"[done - {msg.output_tokens} tokens]")
                    if record.name and record.result:
                        changed_files = list(getattr(session.analytics, "last_turn_changed_files", []) or [])
                        asyncio.ensure_future(
                            _save_memory_snapshot(
                                session,
                                self.parent_session.session_id,
                                record.name,
                                record.task,
                                record.result,
                                changed_files,
                            )
                        )
                    break
                elif isinstance(msg, (SessionEndedEvent, TurnInterruptedEvent)):
                    record.result = "".join(text_buf) or None
                    record.status = "completed"
                    break
                elif isinstance(msg, ErrorEvent):
                    _fwd(f"[error: {msg.message}]")
                    record.status = "failed"
                    break

        except asyncio.CancelledError:
            record.status = "failed"
        except Exception as exc:
            record.status = "failed"
            _fwd(f"[exception: {exc}]")
        finally:
            record.done_event.set()
            try:
                await session.shutdown()
            except Exception:
                pass
