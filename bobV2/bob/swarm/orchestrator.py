from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bob.core.session import BobSession

from bob.swarm.audit import SwarmAuditLog
from bob.swarm.complexity import TaskComplexityAnalyzer
from bob.swarm.models import RiskLevel, SwarmPlan, SwarmRun, SwarmTask
from bob.swarm.progress import SwarmProgressTracker
from bob.swarm.workspace import IsolatedWorkspace


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_PLANNER_SYSTEM = """\
You are a software engineering orchestrator. Given a task and codebase exploration
findings, produce a structured JSON execution plan.

Output ONLY valid JSON (no markdown wrapper) with this exact schema:
{
  "affected_files": ["relative/path/to/file", ...],
  "risk_summary": "one-sentence risk assessment",
  "estimated_changes": "brief scope description, e.g. '4 files, ~150 LOC'",
  "tasks": [
    {
      "id": "t1",
      "role": "implementer",
      "task": "clear description of what this agent must do",
      "deps": [],
      "risk_level": "low",
      "files_to_read": ["relative/path"],
      "files_to_modify": ["relative/path"],
      "tools_needed": ["edit_file", "shell"],
      "estimated_turns": 12
    }
  ]
}

Rules:
- Roles: implementer (writes code), tester (runs/writes tests), reviewer (read-only),
  verifier (runs checks, read+shell only).
- Keep tasks focused. 2-6 tasks is ideal; 15 maximum.
- Always add a reviewer task depending on all implementers.
- Deps are task ids that must complete BEFORE this task starts.
- risk_level: "high" for deletes, schema changes, core logic rewrites.
"""

_PLANNER_RETRY_SUFFIX = """
The previous response was invalid or empty.
Return JSON only.
Do not add commentary.
Do not wrap in markdown fences.
"""

_EXPLORER_TASK = """\
You are an exploration agent for a swarm run. Explore the project to understand
what will be affected by the task below. Use read_file, glob_files, grep_files,
list_dir only — do NOT write anything.

Task to explore: {task}
Project root: {cwd}

At the end output a structured summary with these sections:
## Affected Files
## Key Dependencies
## Risks
## Findings
"""

_AGENT_PROMPT = """\
# Original Task
{original_task}

# Your Assignment ({role})
{task}

# Your Workspace
{workspace_dir}

All reads and writes must use paths inside: {workspace_dir}
{readonly_note}
{files_section}
"""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class SwarmOrchestrator:
    """Drives the full swarm pipeline: explore → plan → authorize → execute → patch."""

    def __init__(self, session: "BobSession"):
        self._session = session

    async def run(self, task: str) -> None:
        session = self._session
        run_id = str(uuid.uuid4())[:8]
        audit = SwarmAuditLog(run_id=run_id, bob_home=session.bob_home, task=task)
        swarm_run = SwarmRun(run_id=run_id, task=task, started_at=time.time())
        swarm_run.audit_path = audit.audit_path

        await self._emit_started(run_id, task)

        try:
            # ── Phase 1: Exploration ──────────────────────────────────────
            await self._emit_progress(run_id, 0, 0, 0, "exploration", "Exploring codebase…")
            audit.log_phase("exploration")
            findings = await self._explore(task, run_id, audit)

            # ── Phase 2: Plan generation ──────────────────────────────────
            await self._emit_progress(run_id, 0, 0, 0, "planning", "Generating execution plan…")
            audit.log_phase("planning")
            plan = await self._generate_plan(task, findings, run_id, audit)
            swarm_run.plan = plan

            # ── Phase 3: Authorization gate ───────────────────────────────
            audit.log_plan_generated(plan.model_dump())
            await self._emit_plan_ready(run_id, plan)

            if not plan.executable:
                message = plan.planner_error or "Planner failed; refusing unsafe fallback execution."
                await self._emit_completed(run_id, False, message)
                audit.log_completed(False, message)
                return

            approved, feedback = await self._wait_for_authorization(run_id)
            audit.log_authorization(approved, feedback)

            if not approved:
                await self._emit_cancelled(run_id, feedback or "User declined")
                return

            await self._emit_authorized(run_id)

            # ── Phase 4: Execution ────────────────────────────────────────
            audit.log_phase("execution")
            tracker = SwarmProgressTracker(
                stall_threshold_seconds=float(
                    getattr(getattr(session.config, "swarm", None), "agent_timeout_seconds", 300)
                )
            )
            self._validate_plan(plan)
            results = await self._execute_plan(plan, run_id, audit, tracker)

            # ── Phase 5: Aggregation ──────────────────────────────────────
            await self._emit_progress(run_id, tracker.total, tracker.done, 0,
                                       "aggregation", "Aggregating patches…")
            audit.log_phase("aggregation")
            patch_text, files_changed = await self._aggregate(results)
            swarm_run.patch_text = patch_text
            swarm_run.files_changed = files_changed

            cleanup = getattr(getattr(session.config, "swarm", None), "workspace_cleanup", True)
            if cleanup:
                for _, _, ws in results:
                    if ws:
                        await asyncio.to_thread(ws.cleanup)

            if not patch_text.strip():
                failed_count = sum(1 for task, _, _ in results if task.status == "failed")
                if failed_count:
                    message = f"Swarm finished with no patch; {failed_count} agent(s) failed."
                    await self._emit_completed(run_id, False, message)
                    audit.log_completed(False, message)
                else:
                    await self._emit_completed(run_id, True, "Swarm finished — no file changes produced.")
                    audit.log_completed(True, "no changes")
                return

            audit.log_patch_ready(files_changed, patch_text)

            # ── Phase 6: Patch delivery ───────────────────────────────────
            summary = self._build_summary(plan, files_changed, results)
            await self._emit_patch_ready(run_id, files_changed, summary, patch_text)
            audit.log_completed(True, f"{len(files_changed)} files changed")

        except asyncio.CancelledError:
            await self._emit_cancelled(run_id, "Interrupted")
            audit.log_completed(False, "cancelled")
            raise
        except Exception as exc:
            await self._emit_completed(run_id, False, f"Error: {exc}")
            audit.log_completed(False, str(exc))

    # ------------------------------------------------------------------
    # Exploration
    # ------------------------------------------------------------------

    async def _explore(self, task: str, run_id: str, audit: SwarmAuditLog) -> str:
        session = self._session
        tm = session.ensure_thread_manager()

        _RO_TOOLS = ["read_file", "glob_files", "grep_files", "list_dir",
                     "web_search", "web_fetch"]

        explorer_tasks = [
            _EXPLORER_TASK.format(task=task, cwd=str(session.cwd)),
            (
                f"Analyze tests, configs, CI scripts, and import graph for:\n{task}\n"
                f"Project root: {session.cwd}\n"
                "Use read_file, glob_files, grep_files, list_dir only. Do NOT write files.\n"
                "Output: ## Test Coverage, ## Config Files, ## Import Graph, ## Risks"
            ),
        ]

        agent_ids: list[str] = []
        for i, atask in enumerate(explorer_tasks):
            aid = await tm.spawn(
                task=atask, model=None, cwd=None,
                name=f"swarm_explore_{run_id}_{i}", parent_agent_id=None,
                role="explorer", allowed_tools=_RO_TOOLS,
                allow_mutating_tools=False, runtime_ttl_seconds=180,
            )
            audit.log_agent_spawned(aid, "explorer", atask[:100], str(session.cwd))
            agent_ids.append(aid)
            await self._emit_progress(run_id, 2, 0, i + 1, "exploration",
                                       f"Explorer {i + 1}/2 running…")

        parts: list[str] = []
        for aid in agent_ids:
            result = await tm.wait_for_agent(aid, timeout=180.0)
            audit.log_agent_completed(aid, "explorer", [], result or "")
            if result:
                parts.append(result)

        return "\n\n---\n\n".join(parts) if parts else "No exploration findings."

    # ------------------------------------------------------------------
    # Plan generation
    # ------------------------------------------------------------------

    async def _generate_plan(self, task: str, findings: str, run_id: str,
                               audit: SwarmAuditLog) -> SwarmPlan:
        session = self._session
        swarm_cfg = getattr(session.config, "swarm", None)
        max_retries = max(1, int(getattr(swarm_cfg, "planning_max_retries", 2)))

        base_user_content = (
            f"# Task\n{task}\n\n"
            f"# Exploration Findings\n{findings[:8000]}\n\n"
            f"# Project Root\n{session.cwd}\n\n"
            "Produce the execution plan JSON now."
        )

        from bob.llm.client import TextDeltaEvent as _TextDelta
        last_error = "planner returned no output"
        raw = ""
        data = None
        attempts_used = 0
        previous_raw = ""
        for attempt in range(1, max_retries + 1):
            attempts_used = attempt
            raw = ""
            user_content = base_user_content
            instructions = _PLANNER_SYSTEM
            if attempt > 1:
                user_content += (
                    "\n\n# Previous Invalid Planner Output\n"
                    f"{previous_raw[:1200] or '<empty>'}\n\n"
                    "Repair the response and return valid JSON only."
                )
                instructions = _PLANNER_SYSTEM + "\n\n" + _PLANNER_RETRY_SUFFIX
            try:
                async for event in session.client.stream_turn(
                    input=[{"role": "user", "content": user_content}],
                    instructions=instructions,
                    tools=[],
                    max_output_tokens=2048,
                    temperature=0.1,
                ):
                    if isinstance(event, _TextDelta):
                        raw += event.delta
            except Exception as exc:
                last_error = str(exc)
                continue

            data = self._parse_json(raw)
            if data is not None:
                break
            previous_raw = raw
            preview = raw.strip()[:120].replace("\n", " ")
            last_error = f"JSON parse error: {preview!r}"

        if data is None:
            return self._fallback_plan(
                task, run_id, findings, last_error, attempts=attempts_used
            )

        tasks: list[SwarmTask] = []
        for rt in data.get("tasks", []):
            try:
                rl = RiskLevel(rt.get("risk_level", "low"))
            except ValueError:
                rl = RiskLevel.LOW
            tasks.append(SwarmTask(
                id=rt.get("id", str(uuid.uuid4())[:4]),
                role=rt.get("role", "implementer"),
                task=rt.get("task", "Implement changes"),
                deps=rt.get("deps", []),
                risk_level=rl,
                files_to_read=rt.get("files_to_read", []),
                files_to_modify=rt.get("files_to_modify", []),
                tools_needed=rt.get("tools_needed", []),
                estimated_turns=int(rt.get("estimated_turns", 10)),
            ))

        if not tasks:
            return self._fallback_plan(task, run_id, findings, "no tasks in plan", attempts=attempts_used)

        return SwarmPlan(
            run_id=run_id,
            original_task=task,
            tasks=tasks,
            total_agents=len(tasks),
            planner_status="planned",
            planner_error="",
            planner_attempts=attempts_used,
            executable=True,
            affected_files=data.get("affected_files", []),
            risk_summary=data.get("risk_summary", ""),
            estimated_changes=data.get("estimated_changes", ""),
            exploration_findings=findings[:2000],
        )

    def _fallback_plan(
        self,
        task: str,
        run_id: str,
        findings: str,
        reason: str,
        *,
        attempts: int,
    ) -> SwarmPlan:
        complexity, complexity_reason = TaskComplexityAnalyzer().classify(task)
        allow_unsafe = bool(
            getattr(getattr(self._session.config, "swarm", None), "allow_unsafe_fallback_execution", False)
        )
        executable = allow_unsafe or complexity.value == "simple"
        risk_summary = f"Fallback plan ({reason[:80]})"
        if not executable:
            risk_summary += " [execution disabled]"
        return SwarmPlan(
            run_id=run_id,
            original_task=task,
            tasks=[
                SwarmTask(id="t1", role="implementer", task=task, risk_level=RiskLevel.MEDIUM),
                SwarmTask(id="t2", role="reviewer",
                          task="Review all changes for correctness.", deps=["t1"]),
            ],
            total_agents=2,
            planner_status="fallback",
            planner_error=(
                f"Planner failed after {attempts} attempt(s): {reason}. "
                f"Task classified as {complexity.value} ({complexity_reason})."
            ),
            planner_attempts=attempts,
            executable=executable,
            affected_files=[],
            risk_summary=risk_summary,
            estimated_changes="Unknown",
            exploration_findings=findings[:2000],
        )

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        text = text.strip()
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        if m:
            text = m.group(1).strip()
        try:
            return json.loads(text)
        except Exception:
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except Exception:
                    pass
        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute_plan(
        self,
        plan: SwarmPlan,
        run_id: str,
        audit: SwarmAuditLog,
        tracker: SwarmProgressTracker,
    ) -> list[tuple[SwarmTask, Optional[str], Optional[IsolatedWorkspace]]]:
        session = self._session
        tm = session.ensure_thread_manager()

        exec_tasks = plan.execution_tasks or plan.tasks
        agent_timeout = int(
            getattr(getattr(session.config, "swarm", None), "agent_timeout_seconds", 300)
        )
        max_parallel = max(1, int(
            getattr(getattr(session.config, "swarm", None), "max_agents", 4)
        ))

        for t in exec_tasks:
            tracker.register(t.id, t.role)

        task_map = {t.id: t for t in exec_tasks}
        ws_map: dict[str, IsolatedWorkspace] = {}
        result_map: dict[str, Optional[str]] = {}
        completed: set[str] = set()
        failed: set[str] = set()
        running: dict[asyncio.Task, str] = {}
        pending = set(task_map.keys())

        await self._emit_progress(run_id, tracker.total, 0, 0, "execution",
                                   f"Preparing {tracker.total} agent tasks…")

        while pending or running:
            # Launch all tasks whose deps are satisfied
            for tid in list(pending):
                if len(running) >= max_parallel:
                    break
                st = task_map[tid]
                failed_deps = [dep for dep in st.deps if dep in failed]
                if failed_deps:
                    st.status = "failed"
                    st.result = f"Skipped because dependency failed: {', '.join(failed_deps)}"
                    result_map[tid] = st.result
                    pending.discard(tid)
                    failed.add(tid)
                    tracker.mark_done(tid)
                    audit.log_agent_completed(tid, st.role, [], st.result)
                    await self._emit_progress(
                        run_id, tracker.total, tracker.done, len(running),
                        "execution", f"Skipped {tid}; dependency failed"
                    )
                    continue
                if any(dep not in completed for dep in st.deps):
                    continue

                seed_files = list(dict.fromkeys(st.files_to_read + st.files_to_modify)) or None
                ws = await asyncio.to_thread(IsolatedWorkspace, session.cwd, seed_files)
                ws_map[tid] = ws

                prompt = _AGENT_PROMPT.format(
                    original_task=plan.original_task,
                    role=st.role,
                    task=st.task,
                    workspace_dir=str(ws.workspace_dir),
                    readonly_note=(
                        "\nIMPORTANT: Do NOT write or modify any files. Read-only exploration only."
                        if st.role in ("reviewer", "verifier") else ""
                    ),
                    files_section=(
                        "\n# Key Files\n" + "\n".join(f"- {f}" for f in
                            (st.files_to_read + st.files_to_modify)[:20])
                        if (st.files_to_read or st.files_to_modify) else ""
                    ),
                )

                allowed = self._tools_for_role(st.role)
                aid = await tm.spawn(
                    task=prompt, model=None,
                    cwd=str(ws.workspace_dir),
                    name=f"swarm_{run_id}_{tid}", parent_agent_id=None,
                    role=st.role, allowed_tools=allowed,
                    allow_mutating_tools=(st.role not in ("reviewer", "verifier")),
                    runtime_ttl_seconds=agent_timeout,
                )
                st.agent_id = aid
                st.workspace_dir = str(ws.workspace_dir)
                st.status = "running"
                audit.log_agent_spawned(aid, st.role, st.task[:100], str(ws.workspace_dir))
                tracker.record_activity(tid)

                async_t = asyncio.create_task(
                    tm.wait_for_agent(aid, timeout=float(agent_timeout))
                )
                running[async_t] = tid
                pending.discard(tid)

                await self._emit_progress(run_id, tracker.total, tracker.done, len(running),
                                           "execution", f"Started {st.role} agent ({tid})")

            if not running:
                if pending:
                    blocked = ", ".join(sorted(pending))
                    raise RuntimeError(f"Swarm execution stalled; unresolved dependencies for: {blocked}")
                break

            done_set, _ = await asyncio.wait(
                set(running.keys()), timeout=2.0, return_when=asyncio.FIRST_COMPLETED
            )
            if not done_set:
                for stalled_id in tracker.check_stalls():
                    st = task_map.get(stalled_id)
                    audit.log_agent_stalled(stalled_id, st.role if st else "")
                    await self._emit_progress(
                        run_id, tracker.total, tracker.done, len(running),
                        "execution", f"Agent task {stalled_id} appears stalled"
                    )
                continue
            for done_t in done_set:
                tid = running.pop(done_t)
                st = task_map[tid]
                try:
                    result = done_t.result()
                    st.result = result
                    result_map[tid] = result
                    if result is None:
                        st.status = "failed"
                        failed.add(tid)
                        result_map[tid] = "Agent timed out or completed without a result."
                    else:
                        st.status = "completed"
                        completed.add(tid)
                except Exception:
                    st.status = "failed"
                    failed.add(tid)
                    result_map[tid] = None

                tracker.mark_done(tid)

                ws = ws_map.get(tid)
                if ws:
                    _, changed_files = await asyncio.to_thread(ws.generate_patch)
                else:
                    changed_files = []
                audit.log_agent_completed(
                    st.agent_id or tid, st.role, changed_files, result_map.get(tid) or ""
                )
                await self._emit_agent_completed(run_id, st.agent_id or tid,
                                                  st.role, changed_files)
                await self._emit_progress(run_id, tracker.total, tracker.done, len(running),
                                           "execution",
                                           f"{tracker.done}/{tracker.total} tasks complete")

        return [(task_map[tid], result_map.get(tid), ws_map.get(tid))
                for tid in task_map]

    @staticmethod
    def _validate_plan(plan: SwarmPlan) -> None:
        tasks = plan.execution_tasks or plan.tasks
        ids = [t.id for t in tasks]
        duplicate_ids = sorted({tid for tid in ids if ids.count(tid) > 1})
        if duplicate_ids:
            raise ValueError(f"Swarm plan has duplicate task ids: {', '.join(duplicate_ids)}")

        task_map = {t.id: t for t in tasks}
        missing = sorted({dep for t in tasks for dep in t.deps if dep not in task_map})
        if missing:
            raise ValueError(f"Swarm plan references missing dependencies: {', '.join(missing)}")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(tid: str) -> None:
            if tid in visited:
                return
            if tid in visiting:
                raise ValueError(f"Swarm plan contains a dependency cycle at {tid}")
            visiting.add(tid)
            for dep in task_map[tid].deps:
                visit(dep)
            visiting.remove(tid)
            visited.add(tid)

        for tid in ids:
            visit(tid)

        readonly_violations = [
            t.id for t in tasks
            if t.role in ("reviewer", "verifier", "explorer") and t.files_to_modify
        ]
        if readonly_violations:
            raise ValueError(
                "Read-only swarm tasks cannot declare files_to_modify: "
                + ", ".join(readonly_violations)
            )

    @staticmethod
    def _tools_for_role(role: str) -> Optional[list[str]]:
        _RO = ["read_file", "glob_files", "grep_files", "list_dir"]
        if role in ("reviewer", "verifier", "explorer"):
            return _RO + ["shell"]
        if role == "tester":
            return _RO + ["shell", "write_file", "edit_file"]
        return None  # implementer gets all tools

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    async def _aggregate(
        self,
        results: list[tuple[SwarmTask, Optional[str], Optional[IsolatedWorkspace]]],
    ) -> tuple[str, list[str]]:
        bundles: list[dict] = []
        all_changed: list[str] = []
        seen: set[str] = set()

        for st, _, ws in results:
            if ws is None or st.role in ("reviewer", "verifier", "explorer"):
                continue
            if st.status != "completed":
                continue
            bundle, changed = await asyncio.to_thread(
                ws.generate_change_bundle,
                agent_id=st.agent_id or st.id,
                role=st.role,
            )
            for f in changed:
                if f not in seen:
                    all_changed.append(f)
                    seen.add(f)
            if changed:
                bundles.append(bundle)

        if not bundles:
            return "", all_changed
        return IsolatedWorkspace.encode_bundles(bundles), all_changed

    def _build_summary(
        self,
        plan: SwarmPlan,
        files_changed: list[str],
        results: list[tuple[SwarmTask, Optional[str], Optional[IsolatedWorkspace]]],
    ) -> str:
        ok = sum(1 for t, _, _ in results if t.status == "completed")
        fail = sum(1 for t, _, _ in results if t.status == "failed")
        lines = [
            f"Swarm completed — {ok}/{len(results)} agents succeeded.",
            f"Files changed: {len(files_changed)}",
        ]
        for f in files_changed[:12]:
            lines.append(f"  · {f}")
        if len(files_changed) > 12:
            lines.append(f"  · …and {len(files_changed) - 12} more")
        if fail:
            lines.append(f"Warning: {fail} agent(s) failed — partial changes only.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Authorization gate
    # ------------------------------------------------------------------

    async def _wait_for_authorization(self, run_id: str) -> tuple[bool, str]:
        session = self._session
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[tuple[bool, str]] = loop.create_future()

        if not hasattr(session, "_pending_swarm_authorizations"):
            session._pending_swarm_authorizations = {}
        session._pending_swarm_authorizations[run_id] = fut

        try:
            return await asyncio.wait_for(fut, timeout=600.0)
        except asyncio.TimeoutError:
            return False, "Authorization window expired"
        finally:
            session._pending_swarm_authorizations.pop(run_id, None)

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    async def _emit(self, msg) -> None:
        from bob.protocol.events import Event
        await self._session._emit(Event(id="swarm", msg=msg))

    async def _emit_started(self, run_id: str, task: str) -> None:
        from bob.protocol.events import SwarmStartedEvent
        await self._emit(SwarmStartedEvent(run_id=run_id, task=task))

    async def _emit_progress(self, run_id: str, total: int, done: int,
                               running_n: int, phase: str, message: str) -> None:
        from bob.protocol.events import SwarmProgressEvent
        await self._emit(SwarmProgressEvent(
            run_id=run_id, agents_total=total, agents_done=done,
            agents_running=running_n, current_phase=phase, message=message,
        ))

    async def _emit_plan_ready(self, run_id: str, plan: SwarmPlan) -> None:
        from bob.protocol.events import SwarmPlanReadyEvent
        await self._emit(SwarmPlanReadyEvent(run_id=run_id, plan=plan.model_dump(mode="json")))

    async def _emit_authorized(self, run_id: str) -> None:
        from bob.protocol.events import SwarmAuthorizedEvent
        await self._emit(SwarmAuthorizedEvent(run_id=run_id))

    async def _emit_agent_completed(self, run_id: str, agent_id: str,
                                     role: str, files_modified: list[str]) -> None:
        from bob.protocol.events import SwarmAgentCompletedEvent
        await self._emit(SwarmAgentCompletedEvent(
            run_id=run_id, agent_id=agent_id, role=role, files_modified=files_modified,
        ))

    async def _emit_patch_ready(self, run_id: str, files_changed: list[str],
                                 summary: str, patch_text: str) -> None:
        from bob.protocol.events import SwarmPatchReadyEvent
        await self._emit(SwarmPatchReadyEvent(
            run_id=run_id, files_changed=files_changed,
            summary=summary, patch_text=patch_text,
        ))

    async def _emit_completed(self, run_id: str, success: bool, message: str) -> None:
        from bob.protocol.events import SwarmCompletedEvent
        await self._emit(SwarmCompletedEvent(run_id=run_id, success=success, message=message))

    async def _emit_cancelled(self, run_id: str, reason: str) -> None:
        from bob.protocol.events import SwarmCancelledEvent
        await self._emit(SwarmCancelledEvent(run_id=run_id, reason=reason))
