"""
ThreadManager - in-process multi-agent orchestration for Bob.

This version adds:
- persistent agent tree metadata (parent/child edges, depth, path, role/name)
- path/name/id agent reference resolution
- depth limits
- canonical close (cascades descendants) and resume behavior
- richer wait/list snapshots
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

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

_TERMINAL_STATES = {"idle", "failed", "closed"}


def _now_ts() -> int:
    import time
    return int(time.time())


def _preview(text: str | None, limit: int = 120) -> str | None:
    if not text:
        return None
    t = text.strip()
    if len(t) <= limit:
        return t
    return t[:limit] + "..."


@dataclass
class PersistedAgentRecord:
    id: str
    status: str
    task: str
    name: Optional[str]
    role: Optional[str]
    path: str
    parent_id: Optional[str]
    depth: int
    cwd: str
    model: Optional[str]
    template: Optional[str]
    created_at_ts: int
    updated_at_ts: int
    closed_at_ts: Optional[int]
    last_result: Optional[str]
    current_task: Optional[str]
    children: list[str]
    task_name: Optional[str] = None
    allowed_tools: Optional[list[str]] = None
    runtime_ttl_seconds: Optional[int] = None
    allow_mutating_tools: bool = True


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
    task: str
    color: str
    name: Optional[str]
    role: Optional[str]
    path: str
    parent_id: Optional[str]
    depth: int
    cwd: str
    model: Optional[str]
    template: Optional[str]
    created_at_ts: int
    updated_at_ts: int
    task_name: Optional[str] = None
    allowed_tools: set[str] | None = None
    runtime_ttl_seconds: Optional[int] = None
    allow_mutating_tools: bool = True
    status: str = "idle"  # idle | queued | running | failed | closed
    last_result: Optional[str] = None
    current_task: Optional[str] = None
    current_task_name: Optional[str] = None
    closed_at_ts: Optional[int] = None
    children: set[str] = field(default_factory=set)
    session: "BobSession | None" = None
    task_ref: Optional[asyncio.Task] = None
    queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)
    done_event: asyncio.Event = field(default_factory=asyncio.Event)

    def to_snapshot(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "status": self.status,
            "path": self.path,
            "parent_id": self.parent_id,
            "depth": self.depth,
            "cwd": self.cwd,
            "model": self.model,
            "template": self.template,
            "task_name": self.task_name,
            "current_task_name": self.current_task_name,
            "allowed_tools": sorted(self.allowed_tools) if self.allowed_tools else None,
            "runtime_ttl_seconds": self.runtime_ttl_seconds,
            "allow_mutating_tools": self.allow_mutating_tools,
            "task": self.task,
            "current_task": self.current_task,
            "queued_tasks": self.queue.qsize(),
            "result_preview": _preview(self.last_result),
            "created_at_ts": self.created_at_ts,
            "updated_at_ts": self.updated_at_ts,
            "closed_at_ts": self.closed_at_ts,
            "children": sorted(self.children),
        }

    def to_persisted(self) -> PersistedAgentRecord:
        return PersistedAgentRecord(
            id=self.id,
            status=self.status,
            task=self.task,
            task_name=self.task_name,
            name=self.name,
            role=self.role,
            path=self.path,
            parent_id=self.parent_id,
            depth=self.depth,
            cwd=self.cwd,
            model=self.model,
            template=self.template,
            allowed_tools=sorted(self.allowed_tools) if self.allowed_tools else None,
            runtime_ttl_seconds=self.runtime_ttl_seconds,
            allow_mutating_tools=self.allow_mutating_tools,
            created_at_ts=self.created_at_ts,
            updated_at_ts=self.updated_at_ts,
            closed_at_ts=self.closed_at_ts,
            last_result=self.last_result,
            current_task=self.current_task,
            children=sorted(self.children),
        )


class ThreadManager:
    """Manages a tree of sub-agent sessions for one parent Bob session."""

    def __init__(self, parent_session: "BobSession") -> None:
        self.parent_session = parent_session
        self._agents: dict[str, AgentRecord] = {}
        self._color_index = 0
        self._root_child_counter = 0
        self._child_counters: dict[str, int] = {}
        self._state_version = 0
        self._state_event: asyncio.Event = asyncio.Event()
        self._persist_path = self._agent_tree_path()
        self._load_tree()

    def _agent_tree_path(self) -> Path:
        base = self.parent_session.bob_home / "agent_trees"
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{self.parent_session.session_id}.json"

    def _bump_state(self) -> None:
        self._state_version += 1
        old_event = self._state_event
        self._state_event = asyncio.Event()
        old_event.set()

    def _persist_tree(self) -> None:
        try:
            payload = {
                "parent_session_id": self.parent_session.session_id,
                "updated_at_ts": _now_ts(),
                "agents": [asdict(r.to_persisted()) for r in self._agents.values()],
            }
            self._persist_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_tree(self) -> None:
        if not self._persist_path.exists():
            return
        try:
            payload = json.loads(self._persist_path.read_text(encoding="utf-8"))
            agents = payload.get("agents", [])
            for raw in agents:
                pid = raw.get("id")
                if not pid:
                    continue
                rec = AgentRecord(
                    id=str(pid),
                    task=str(raw.get("task", "")),
                    task_name=raw.get("task_name"),
                    color=_COLOR_PALETTE[self._color_index % len(_COLOR_PALETTE)],
                    name=raw.get("name"),
                    role=raw.get("role"),
                    path=str(raw.get("path") or pid),
                    parent_id=raw.get("parent_id"),
                    depth=int(raw.get("depth", 1) or 1),
                    cwd=str(raw.get("cwd") or self.parent_session.cwd),
                    model=raw.get("model"),
                    template=raw.get("template"),
                    allowed_tools=set(raw.get("allowed_tools") or []) or None,
                    runtime_ttl_seconds=(
                        int(raw["runtime_ttl_seconds"])
                        if raw.get("runtime_ttl_seconds") is not None
                        else None
                    ),
                    allow_mutating_tools=bool(raw.get("allow_mutating_tools", True)),
                    created_at_ts=int(raw.get("created_at_ts", _now_ts())),
                    updated_at_ts=int(raw.get("updated_at_ts", _now_ts())),
                    status="closed",  # persisted records are cold; resume explicitly to reactivate
                    last_result=raw.get("last_result"),
                    current_task=raw.get("current_task"),
                    current_task_name=raw.get("current_task_name"),
                    closed_at_ts=raw.get("closed_at_ts"),
                )
                rec.children = set(raw.get("children") or [])
                rec.done_event.set()
                self._agents[rec.id] = rec
                self._color_index += 1

            # Rebuild parent/child links from parent_id to keep tree shape canonical.
            for rec in self._agents.values():
                if rec.parent_id and rec.parent_id in self._agents:
                    self._agents[rec.parent_id].children.add(rec.id)

            # Rebuild path counters so future spawns keep unique path addressing.
            for rec in self._agents.values():
                parts = [p for p in rec.path.split("/") if p]
                if not parts:
                    continue
                last = parts[-1]
                if not last.startswith("a"):
                    continue
                try:
                    idx = int(last[1:])
                except ValueError:
                    continue
                if rec.parent_id is None and len(parts) == 1:
                    self._root_child_counter = max(self._root_child_counter, idx)
                if rec.parent_id:
                    self._child_counters[rec.parent_id] = max(
                        self._child_counters.get(rec.parent_id, 0),
                        idx,
                    )
        except Exception:
            # If persisted state is malformed, ignore and rebuild from live state.
            self._agents = {}

    def _next_path(self, parent: AgentRecord | None) -> str:
        if parent is None:
            self._root_child_counter += 1
            return f"a{self._root_child_counter}"
        current = self._child_counters.get(parent.id, 0) + 1
        self._child_counters[parent.id] = current
        return f"{parent.path}/a{current}"

    def _resolve(self, agent_ref: str) -> AgentRecord:
        rec = self._agents.get(agent_ref)
        if rec is not None:
            return rec

        by_path = [r for r in self._agents.values() if r.path == agent_ref]
        if len(by_path) == 1:
            return by_path[0]
        if len(by_path) > 1:
            raise KeyError(f"Ambiguous agent path '{agent_ref}'")

        by_name = [r for r in self._agents.values() if r.name == agent_ref]
        if len(by_name) == 1:
            return by_name[0]
        if len(by_name) > 1:
            raise KeyError(f"Ambiguous agent name '{agent_ref}'")

        raise KeyError(f"No sub-agent with reference '{agent_ref}'")

    def _descendants(self, agent_id: str) -> list[str]:
        out: list[str] = []
        stack = [agent_id]
        seen: set[str] = set()
        while stack:
            cur = stack.pop()
            rec = self._agents.get(cur)
            if rec is None:
                continue
            for child in rec.children:
                if child in seen:
                    continue
                seen.add(child)
                out.append(child)
                stack.append(child)
        return out

    async def _create_runtime_session(self, rec: AgentRecord) -> None:
        from bob.core.session import BobSession
        from bob.core.agent_templates import get_template
        from bob.core.agent_memory import load_snapshot

        config = self.parent_session.config.model_copy(deep=True)
        if rec.model:
            config = config.model_copy(update={"model": rec.model})

        agent_cwd = Path(rec.cwd)
        session = BobSession(config=config, cwd=agent_cwd, ephemeral=True)
        await session.start()

        tmpl = get_template(rec.template) if rec.template else None
        allowed = set(rec.allowed_tools or [])
        if not allowed and tmpl and tmpl.allowed_tools:
            allowed = set(tmpl.allowed_tools)
        if allowed:
            all_names = list(session.tool_registry._tools.keys())
            for tname in all_names:
                if tname not in allowed:
                    session.tool_registry.unregister(tname)
            session._allowed_tools = set(allowed)
        else:
            session._allowed_tools = None

        session._allow_mutating_tools = bool(rec.allow_mutating_tools)

        if tmpl and tmpl.system_prompt_suffix:
            session._system_prompt = (
                (session._system_prompt or "") + "\n\n" + tmpl.system_prompt_suffix
            )

        if rec.name:
            prior = load_snapshot(self.parent_session.session_id, rec.name)
            if prior:
                session._system_prompt = (
                    (session._system_prompt or "")
                    + f"\n\n## Memory from prior session\n{prior}"
                )

        rec.session = session
        if rec.task_ref is None or rec.task_ref.done():
            rec.task_ref = asyncio.create_task(self._agent_worker(rec.id))

    async def spawn(
        self,
        task: str,
        model: Optional[str] = None,
        cwd: Optional[str] = None,
        template: Optional[str] = None,
        name: Optional[str] = None,
        parent_agent_id: Optional[str] = None,
        role: Optional[str] = None,
        max_depth: int = 5,
        allowed_tools: Optional[list[str]] = None,
        runtime_ttl_seconds: Optional[int] = 1800,
        allow_mutating_tools: bool = True,
        task_name: Optional[str] = None,
    ) -> str:
        """Spawn a sub-agent and enqueue the initial task."""
        parent = self._resolve(parent_agent_id) if parent_agent_id else None
        depth = (parent.depth + 1) if parent else 1
        if depth > max_depth:
            raise ValueError(f"Agent depth limit reached (max_depth={max_depth})")

        agent_id = str(uuid.uuid4())[:8]
        color = _COLOR_PALETTE[self._color_index % len(_COLOR_PALETTE)]
        self._color_index += 1
        now = _now_ts()
        ttl = None
        if runtime_ttl_seconds is not None:
            try:
                ttl = max(1, int(runtime_ttl_seconds))
            except Exception:
                ttl = 1800
        rec = AgentRecord(
            id=agent_id,
            task=task,
            task_name=task_name,
            color=color,
            name=name,
            role=role,
            path=self._next_path(parent),
            parent_id=parent.id if parent else None,
            depth=depth,
            cwd=str(Path(cwd).resolve()) if cwd else str(self.parent_session.cwd),
            model=model,
            template=template,
            allowed_tools=set(allowed_tools or []) or None,
            runtime_ttl_seconds=ttl,
            allow_mutating_tools=allow_mutating_tools,
            created_at_ts=now,
            updated_at_ts=now,
        )
        rec.done_event.set()
        self._agents[agent_id] = rec
        if parent:
            parent.children.add(agent_id)
            parent.updated_at_ts = now

        await self._create_runtime_session(rec)
        await self.assign_task(agent_id=agent_id, task=task, task_name=task_name)
        self._bump_state()
        self._persist_tree()
        return agent_id

    async def assign_task(
        self,
        agent_id: str,
        task: str,
        *,
        task_name: Optional[str] = None,
        interrupt_running: bool = False,
        clear_queue: bool = False,
    ) -> dict:
        rec = self._resolve(agent_id)
        if rec.status == "closed":
            raise ValueError(f"Agent '{agent_id}' is closed; call resume_agent first")

        if rec.session is None:
            await self._create_runtime_session(rec)

        if interrupt_running and rec.session is not None:
            from bob.protocol.ops import InterruptOp
            await rec.session.submit(InterruptOp(type="interrupt"))

        if clear_queue:
            try:
                while True:
                    rec.queue.get_nowait()
                    rec.queue.task_done()
            except asyncio.QueueEmpty:
                pass

        await self._enqueue_item(
            rec=rec,
            text=task,
            kind="task",
            task_name=task_name,
        )
        return rec.to_snapshot()

    async def send_message(self, agent_id: str, message: str) -> str:
        rec = self._resolve(agent_id)
        if rec.status == "closed":
            raise ValueError(f"Agent '{agent_id}' is closed; call resume_agent first")
        await self._enqueue_item(rec=rec, text=message, kind="message")
        return f"Message delivered to agent {rec.id} ({rec.path})"

    async def _enqueue_item(
        self,
        *,
        rec: AgentRecord,
        text: str,
        kind: str,
        task_name: Optional[str] = None,
    ) -> None:
        rec.updated_at_ts = _now_ts()
        if kind == "task":
            rec.task = text
            rec.task_name = task_name
        rec.done_event.clear()
        if rec.status in {"idle", "failed"}:
            rec.status = "queued"
        await rec.queue.put(
            {
                "kind": kind,
                "text": text,
                "task_name": task_name,
                "queued_at_ts": _now_ts(),
            }
        )
        self._bump_state()
        self._persist_tree()

    async def resume_agent(
        self,
        agent_id: str,
        *,
        task: Optional[str] = None,
    ) -> dict:
        rec = self._resolve(agent_id)
        if rec.status in {"closed", "failed"}:
            rec.status = "idle"
            rec.closed_at_ts = None
            rec.updated_at_ts = _now_ts()
            await self._create_runtime_session(rec)

        if rec.session is None:
            await self._create_runtime_session(rec)

        if task:
            await self.assign_task(agent_id=rec.id, task=task)
        self._bump_state()
        self._persist_tree()
        return rec.to_snapshot()

    def _wait_state_reached(self, rec: AgentRecord, target_states: set[str]) -> bool:
        if rec.status not in target_states:
            return False
        # "idle"/"failed" only count as done if there is no active or queued work.
        if rec.status in {"idle", "failed"}:
            if rec.current_task is not None:
                return False
            if rec.queue.qsize() > 0:
                return False
        return True

    async def wait_for_agent(
        self, agent_id: str, timeout: Optional[float] = None
    ) -> Optional[str]:
        rec = self._resolve(agent_id)
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else (loop.time() + timeout)
        while not self._wait_state_reached(rec, _TERMINAL_STATES):
            if deadline is not None and loop.time() >= deadline:
                return None
            waiter = self._state_event
            remaining = None if deadline is None else max(0.0, deadline - loop.time())
            try:
                if remaining is None:
                    await waiter.wait()
                else:
                    await asyncio.wait_for(waiter.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
        return rec.last_result

    async def wait_for_agents(
        self,
        agent_refs: list[str],
        *,
        timeout: Optional[float] = None,
        wait_for_states: Optional[set[str]] = None,
        any_target: bool = True,
    ) -> dict:
        if not agent_refs:
            raise ValueError("agent_refs must not be empty")
        target_states = wait_for_states or _TERMINAL_STATES
        recs = [self._resolve(ref) for ref in agent_refs]
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else (loop.time() + timeout)

        def done() -> tuple[bool, Optional[str]]:
            matched = [r for r in recs if self._wait_state_reached(r, target_states)]
            if any_target:
                return (len(matched) > 0, matched[0].id if matched else None)
            return (len(matched) == len(recs), matched[0].id if matched else None)

        matched_id: Optional[str] = None
        while True:
            ok, matched_id = done()
            if ok:
                break
            if deadline is not None and loop.time() >= deadline:
                break
            waiter = self._state_event
            remaining = None if deadline is None else max(0.0, deadline - loop.time())
            try:
                if remaining is None:
                    await waiter.wait()
                else:
                    await asyncio.wait_for(waiter.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                break

        snapshots = {r.id: r.to_snapshot() for r in recs}
        timed_out = matched_id is None and not done()[0]
        return {
            "timed_out": timed_out,
            "matched_agent_id": matched_id,
            "agents": snapshots,
        }

    async def close_agent(self, agent_id: str, reason: Optional[str] = None) -> None:
        rec = self._resolve(agent_id)
        # Canonical close semantics: close descendants first.
        descendants = self._descendants(rec.id)
        for child_id in descendants:
            child = self._agents.get(child_id)
            if child and child.status != "closed":
                await self._close_single(child, reason=f"parent_closed:{rec.id}")
        await self._close_single(rec, reason=reason)

    async def _close_single(self, rec: AgentRecord, reason: Optional[str]) -> None:
        # Drop any pending tasks; canonical close discards queue state.
        try:
            while True:
                rec.queue.get_nowait()
                rec.queue.task_done()
        except asyncio.QueueEmpty:
            pass

        rec.status = "closed"
        rec.current_task = None
        rec.closed_at_ts = _now_ts()
        rec.updated_at_ts = rec.closed_at_ts
        rec.done_event.set()

        if rec.task_ref and not rec.task_ref.done():
            rec.task_ref.cancel()
            try:
                await rec.task_ref
            except (asyncio.CancelledError, Exception):
                pass

        if rec.session is not None:
            try:
                await rec.session.shutdown()
            except Exception:
                pass
            rec.session = None

        self._bump_state()
        self._persist_tree()
        if reason:
            try:
                from bob.protocol.events import Event, InfoEvent
                await self.parent_session._emit(Event(
                    id="subagent",
                    msg=InfoEvent(type="info", message=f"[agent {rec.id}] closed: {reason}"),
                ))
            except Exception:
                pass

    def list_agents(self, include_completed: bool = False) -> list[dict]:
        """Return descriptors for tracked agents with enhanced metadata."""
        out = []
        for rec in sorted(self._agents.values(), key=lambda r: r.created_at_ts):
            if not include_completed and rec.status == "closed":
                continue
            out.append(rec.to_snapshot())
        return out

    async def shutdown_all(self) -> None:
        """Close all agents - called on parent session shutdown."""
        for rec in list(self._agents.values()):
            if rec.status != "closed":
                try:
                    await self._close_single(rec, reason="parent shutdown")
                except Exception:
                    pass

    async def _agent_worker(self, agent_id: str) -> None:
        """Run queued tasks for one agent session until closed."""
        rec = self._resolve(agent_id)
        color = rec.color
        short_id = agent_id[:6]

        async def _fwd(text: str) -> None:
            from bob.protocol.events import Event, InfoEvent
            msg = InfoEvent(
                type="info",
                message=f"[{color}{short_id}{_RST}] {text}",
            )
            try:
                await self.parent_session._emit(Event(id="subagent", msg=msg))
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

            while rec.status != "closed":
                queued = await rec.queue.get()
                if isinstance(queued, dict):
                    kind = str(queued.get("kind", "task"))
                    task = str(queued.get("text", ""))
                    current_task_name = queued.get("task_name")
                else:
                    kind = "task"
                    task = str(queued)
                    current_task_name = None
                try:
                    if rec.status == "closed":
                        break
                    if rec.session is None:
                        await self._create_runtime_session(rec)

                    rec.status = "running"
                    rec.current_task = task
                    rec.current_task_name = current_task_name if kind == "task" else None
                    rec.updated_at_ts = _now_ts()
                    rec.done_event.clear()
                    self._bump_state()
                    self._persist_tree()

                    await rec.session.submit(
                        UserTurnOp(items=[TextUserInput(type="text", text=task)])
                    )

                    text_buf: list[str] = []
                    failure: Optional[str] = None
                    start_ts = asyncio.get_running_loop().time()
                    deadline_ts = (
                        start_ts + rec.runtime_ttl_seconds
                        if rec.runtime_ttl_seconds is not None and rec.runtime_ttl_seconds > 0
                        else None
                    )
                    events_iter = rec.session.events().__aiter__()
                    while True:
                        try:
                            if deadline_ts is None:
                                event = await events_iter.__anext__()
                            else:
                                remaining = deadline_ts - asyncio.get_running_loop().time()
                                if remaining <= 0:
                                    raise asyncio.TimeoutError
                                event = await asyncio.wait_for(events_iter.__anext__(), timeout=remaining)
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError:
                            failure = (
                                f"Agent runtime exceeded ttl={rec.runtime_ttl_seconds}s "
                                f"for task '{(rec.current_task_name or task)[:80]}'"
                            )
                            rec.last_result = "".join(text_buf).strip() or rec.last_result
                            rec.status = "failed"
                            rec.current_task = None
                            rec.current_task_name = None
                            rec.updated_at_ts = _now_ts()
                            await _fwd(f"[error: {failure}]")
                            break

                        msg = event.msg
                        if isinstance(msg, TextDeltaEvent):
                            text_buf.append(msg.delta)
                            await _fwd(msg.delta)
                        elif isinstance(msg, TurnEndedEvent):
                            rec.last_result = "".join(text_buf).strip() or None
                            rec.status = "idle"
                            rec.current_task = None
                            rec.current_task_name = None
                            rec.updated_at_ts = _now_ts()
                            await _fwd(f"[done - {msg.output_tokens} tokens]")
                            if rec.name and rec.last_result:
                                changed_files = list(getattr(rec.session.analytics, "last_turn_changed_files", []) or [])
                                asyncio.create_task(
                                    _save_memory_snapshot(
                                        rec.session,
                                        self.parent_session.session_id,
                                        rec.name,
                                        task,
                                        rec.last_result,
                                        changed_files,
                                    )
                                )
                            break
                        elif isinstance(msg, (SessionEndedEvent, TurnInterruptedEvent)):
                            rec.last_result = "".join(text_buf).strip() or rec.last_result
                            rec.status = "idle"
                            rec.current_task = None
                            rec.current_task_name = None
                            rec.updated_at_ts = _now_ts()
                            break
                        elif isinstance(msg, ErrorEvent):
                            failure = msg.message
                            rec.last_result = "".join(text_buf).strip() or rec.last_result
                            rec.status = "failed"
                            rec.current_task = None
                            rec.current_task_name = None
                            rec.updated_at_ts = _now_ts()
                            await _fwd(f"[error: {msg.message}]")
                            break

                    # If additional tasks are queued, keep this agent non-idle between runs.
                    if rec.status in {"idle", "failed"} and rec.queue.qsize() > 0:
                        rec.status = "queued"

                    rec.done_event.set()
                    self._bump_state()
                    self._persist_tree()
                    if failure:
                        # Keep worker alive for resume/assign; just continue.
                        continue
                finally:
                    rec.queue.task_done()

        except asyncio.CancelledError:
            rec.status = "closed"
            rec.closed_at_ts = _now_ts()
            rec.updated_at_ts = rec.closed_at_ts
            rec.current_task = None
            rec.current_task_name = None
            rec.done_event.set()
            self._bump_state()
            self._persist_tree()
            raise
        except Exception as exc:
            rec.status = "failed"
            rec.current_task = None
            rec.current_task_name = None
            rec.updated_at_ts = _now_ts()
            rec.done_event.set()
            self._bump_state()
            self._persist_tree()
            try:
                await _fwd(f"[exception: {exc}]")
            except Exception:
                pass
