from __future__ import annotations

import asyncio
from dataclasses import replace
import re
import shlex
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from bob.llm.client import ToolCallEvent
from bob.protocol.config_types import AskForApproval, ExecCommandSource, ExecCommandStatus, ReviewDecision
from bob.protocol.events import (
    ExecApprovalRequestedEvent,
    ExecApprovalResolvedEvent,
    ExecCompletedEvent,
    ExecOutputEvent,
    ExecStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    TurnInterruptedEvent,
)

CommandApprovalFn = Callable[[list[str], Any, set[str], Any], bool]
EscalationCheckFn = Callable[[list[str]], str | None]


class TurnAbortRequested(Exception):
    pass


class ToolOrchestrator:
    """Centralized execution path for model tool calls.

    Handles:
    - plan-mode mutating tool blocking
    - network approval preflight for networked tools
    - parallel/sequential routing from per-tool capabilities
    - generic tool dispatch
    - shell execution strategy and approval flow
    """

    def __init__(
        self,
        *,
        session: Any,
        emit: Callable[[Any], Awaitable[None]],
        cancel_event: asyncio.Event,
        turn_id: str,
        on_output_delta: Callable[[str, str], Awaitable[None]],
        on_plan_update: Callable[[Any], Awaitable[None]],
        session_approved_commands: set[str],
        needs_approval_fn: CommandApprovalFn,
        detect_escalation_fn: EscalationCheckFn,
    ) -> None:
        self.session = session
        self.emit = emit
        self.cancel_event = cancel_event
        self.turn_id = turn_id
        self.on_output_delta = on_output_delta
        self.on_plan_update = on_plan_update
        self.session_approved_commands = session_approved_commands
        self.needs_approval_fn = needs_approval_fn
        self.detect_escalation_fn = detect_escalation_fn

    async def execute_calls(self, tool_calls: list[Any]) -> list[dict]:
        tool_results: list[dict] = []
        if not tool_calls:
            return tool_results

        allowed_calls = await self._filter_plan_mode(tool_calls, tool_results)
        if not allowed_calls:
            return tool_results

        approved_calls = await self._filter_network_approval(allowed_calls, tool_results)
        if not approved_calls:
            return tool_results

        policy_calls = await self._filter_tool_policy(approved_calls, tool_results)
        if not policy_calls:
            return tool_results

        policy_calls = await self._enforce_parallel_understanding_delegation(policy_calls, tool_results)
        if not policy_calls:
            return tool_results

        policy_calls, task_batches = await self._prepare_task_batches(policy_calls, tool_results)
        if not policy_calls:
            return tool_results

        parallel_calls: list[Any] = []
        sequential_calls: list[Any] = []
        for tc in policy_calls:
            caps = self.session.tool_registry.get_tool_capabilities(tc.name)
            if caps.supports_parallel and not caps.is_mutating:
                parallel_calls.append(tc)
            else:
                sequential_calls.append(tc)

        if parallel_calls:
            parallel_results = await asyncio.gather(
                *[self._execute_single(tc, task_batches.get(tc.id)) for tc in parallel_calls],
                return_exceptions=False,
            )
            tool_results.extend([r for r in parallel_results if r is not None])

        for tc in sequential_calls:
            if self.cancel_event.is_set():
                break
            result = await self._execute_single(tc, task_batches.get(tc.id))
            if result is not None:
                tool_results.append(result)

        # Notify after the full batch completes
        from bob.protocol.config_types import HookEventName
        import asyncio as _asyncio
        _asyncio.create_task(self.session.hook_runner.run_hooks(
            HookEventName.POST_TOOL_BATCH,
            {"count": len(tool_results), "turn_id": self.turn_id},
        ))

        return tool_results

    async def _filter_plan_mode(self, tool_calls: list[Any], tool_results: list[dict]) -> list[Any]:
        if not getattr(self.session, "_plan_mode", False):
            return tool_calls

        allowed: list[Any] = []
        for tc in tool_calls:
            caps = self.session.tool_registry.get_tool_capabilities(tc.name)
            if not caps.is_mutating:
                allowed.append(tc)
                continue

            message = (
                f"Tool '{tc.name}' blocked in Plan mode. "
                "Only non-mutating tools are available. Use exit_plan_mode to unlock."
            )
            await self.emit(ToolCallStartedEvent(
                type="tool_call_started",
                tool_call_id=tc.id,
                tool_name=tc.name,
                tool_input=tc.input,
            ))
            await self.emit(ToolCallCompletedEvent(
                type="tool_call_completed",
                tool_call_id=tc.id,
                tool_name=tc.name,
                output=message,
                duration_ms=0,
            ))
            tool_results.append({
                "type": "function_call_output",
                "call_id": tc.id,
                "output": message,
            })
        return allowed

    def _extract_network_target(self, tool_name: str, tool_input: dict) -> tuple[str, str]:
        if tool_name == "web_search":
            return (
                f"duckduckgo.com/search?q={tool_input.get('query', '')}",
                "duckduckgo.com",
            )

        url = str(tool_input.get("url", "") or "")
        if not url:
            return "", ""
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            domain = parsed.netloc or url.split("/")[0]
        except Exception:
            domain = url[:50]
        return url, domain

    async def _filter_network_approval(self, tool_calls: list[Any], tool_results: list[dict]) -> list[Any]:
        approved: list[Any] = []
        for tc in tool_calls:
            caps = self.session.tool_registry.get_tool_capabilities(tc.name)
            if not caps.requires_network_approval:
                approved.append(tc)
                continue

            url, domain = self._extract_network_target(tc.name, tc.input)
            req_id = str(uuid.uuid4())[:12]
            ok = await self.session.get_network_approval(req_id, url, domain, tool_name=tc.name)
            if ok:
                approved.append(tc)
                continue

            message = f"Network access to '{tc.input.get('url', tc.input.get('query', ''))}' was denied by user."
            await self.emit(ToolCallStartedEvent(
                type="tool_call_started",
                tool_call_id=tc.id,
                tool_name=tc.name,
                tool_input=tc.input,
            ))
            await self.emit(ToolCallCompletedEvent(
                type="tool_call_completed",
                tool_call_id=tc.id,
                tool_name=tc.name,
                output=message,
                duration_ms=0,
            ))
            tool_results.append({
                "type": "function_call_output",
                "call_id": tc.id,
                "output": message,
            })

        return approved

    def _read_only_shell_command(self, tool_input: dict) -> bool:
        from bob.core.exec_policy import is_safe_command

        raw_cmd = tool_input.get("command", [])
        if isinstance(raw_cmd, str):
            try:
                cmd = shlex.split(raw_cmd)
            except ValueError:
                cmd = raw_cmd.split()
        else:
            cmd = [str(x) for x in raw_cmd]
        cmd, _ = self._normalize_windows_shell_command(cmd)
        if is_safe_command(cmd):
            return True
        if not cmd:
            return True
        cmd0 = cmd[0].lower()
        cmd1 = cmd[1].lower() if len(cmd) > 1 else ""
        read_only_prefixes = {
            "pytest",
            "npm test",
            "pnpm test",
            "yarn test",
            "python -m",
            "python3 -m",
            "go test",
            "cargo test",
        }
        prefix = f"{cmd0} {cmd1}".strip()
        if prefix in read_only_prefixes:
            return True
        if cmd0 in {"pytest"}:
            return True
        if cmd0 in {"python", "python3"} and cmd1 == "-m":
            return True
        return False

    @staticmethod
    def _normalize_windows_shell_command(command: list[str]) -> tuple[list[str], str | None]:
        if not command:
            return command, None

        cmd0 = str(command[0]).lower()
        if cmd0 != "dir":
            return command, None

        flags = {str(part).lower() for part in command[1:] if str(part).startswith("/")}
        if not ("/s" in flags or "/b" in flags):
            return command, None

        paths = [str(part) for part in command[1:] if not str(part).startswith("/")]
        normalized = ["Get-ChildItem"]
        if "/s" in flags:
            normalized.append("-Recurse")
        if "/b" in flags:
            normalized.append("-Name")
        if paths:
            normalized.extend(paths)
        return normalized, "normalized_windows_dir_flags"

    async def _filter_tool_policy(self, tool_calls: list[Any], tool_results: list[dict]) -> list[Any]:
        allowed_tools: set[str] | None = getattr(self.session, "_allowed_tools", None)
        allow_mutating = bool(getattr(self.session, "_allow_mutating_tools", True))
        if allowed_tools is None and allow_mutating:
            return tool_calls

        allowed: list[Any] = []
        for tc in tool_calls:
            caps = self.session.tool_registry.get_tool_capabilities(tc.name)
            blocked_reason: str | None = None

            if allowed_tools is not None and tc.name not in allowed_tools:
                blocked_reason = (
                    f"Tool '{tc.name}' blocked by agent policy (not in allowed_tools)."
                )
            elif not allow_mutating:
                if tc.name == "shell":
                    if not self._read_only_shell_command(tc.input):
                        blocked_reason = (
                            "Shell command blocked by read-only mode policy. "
                            "Only safe read-only commands are allowed."
                        )
                elif caps.is_mutating:
                    blocked_reason = (
                        f"Tool '{tc.name}' blocked by read-only mode policy "
                        "(mutating tools disabled)."
                    )

            if blocked_reason:
                await self.emit(ToolCallStartedEvent(
                    type="tool_call_started",
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    tool_input=tc.input,
                ))
                await self.emit(ToolCallCompletedEvent(
                    type="tool_call_completed",
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    output=blocked_reason,
                    duration_ms=0,
                ))
                tool_results.append({
                    "type": "function_call_output",
                    "call_id": tc.id,
                    "output": blocked_reason,
                })
                continue

            allowed.append(tc)

        return allowed

    async def _build_tool_context(self) -> Any:
        from bob.core.session import ToolContext

        ctx = ToolContext(self.session)
        ctx.on_output_delta = self.on_output_delta
        ctx.on_plan_update = self.on_plan_update
        ctx.on_request_user_input = self.session.request_user_input
        return ctx

    def _extract_parallel_understanding_targets(self) -> list[str]:
        prompt = str(getattr(self.session, "_current_prompt_text", "") or "").strip()
        if not prompt:
            return []

        match = re.search(
            r"\bboth\s+(?:the\s+)?(?P<left>.+?)\s+and\s+(?:the\s+)?(?P<right>.+?)(?:[.!?\n]|$)",
            prompt,
            flags=re.IGNORECASE,
        )
        if match:
            left = re.sub(r"\s+", " ", match.group("left")).strip(" ,")
            right = re.sub(r"\s+", " ", match.group("right")).strip(" ,")
            if left and right:
                return [left, right]

        prompt_lower = prompt.lower()
        if "bob v2" in prompt_lower and "opencode" in prompt_lower:
            return ["Bob V2 Project", "OpenCode Project"]
        return []

    @staticmethod
    def _make_understanding_task_call(target: str, *, workspace_root: Path, in_workspace_hint: bool) -> ToolCallEvent:
        if in_workspace_hint:
            prompt = (
                f"You are exploring {target} in the current workspace at {workspace_root}.\n\n"
                f"Build a full understanding of {target}: what it is, how it looks, how it works, "
                "its architecture, key modules, configuration, tests, workflows, and notable implementation details.\n"
                "Start from top-level structure and key entrypoints, then read concrete files.\n\n"
                "Return a comprehensive, evidence-backed summary with concrete file paths."
            )
        else:
            prompt = (
                f"You are researching {target} for a broad comparison request.\n\n"
                f"Understand what {target} is, how it works, its architecture, key components, main workflows, "
                "and any official docs or source locations.\n"
                "If it exists in the current workspace, inspect local files. Otherwise, use web_search/web_fetch "
                "to research it externally.\n\n"
                "Return a comprehensive, evidence-backed summary with concrete file paths or URLs."
            )
        return ToolCallEvent(
            id=f"auto_task_{uuid.uuid4().hex[:12]}",
            name="task",
            input={
                "description": f"Explore {target}"[:80],
                "prompt": prompt,
                "subagent_type": "explore",
            },
        )

    def _build_parallel_understanding_task_pair(self) -> list[Any] | None:
        targets = self._extract_parallel_understanding_targets()
        if len(targets) != 2:
            return None
        cwd_text = str(getattr(self.session, "cwd", "") or "").lower()
        left, right = targets
        left_in_workspace = any(token in cwd_text for token in left.lower().split()[:2])
        right_in_workspace = any(token in cwd_text for token in right.lower().split()[:2])
        workspace_root = Path(getattr(self.session, "cwd", Path(".")))
        return [
            self._make_understanding_task_call(left, workspace_root=workspace_root, in_workspace_hint=left_in_workspace or not right_in_workspace),
            self._make_understanding_task_call(right, workspace_root=workspace_root, in_workspace_hint=right_in_workspace and not left_in_workspace),
        ]

    @staticmethod
    def _replace_tool_call(tc: Any, *, input: dict[str, Any]) -> Any:
        if isinstance(tc, ToolCallEvent):
            return replace(tc, input=input)
        return type(tc)(
            **{
                **getattr(tc, "__dict__", {}),
                "input": input,
            }
        )

    def _needs_parallel_understanding_delegation(self, tool_calls: list[Any]) -> bool:
        prompt = str(getattr(self.session, "_current_prompt_text", "") or "").lower()
        if not prompt:
            return False
        if any(tc.name == "task" for tc in tool_calls):
            return False

        broad_markers = (
            "full understanding",
            "understand",
            "understanding",
            "analyze",
            "analysis",
            "map out",
            "overview",
        )
        compare_markers = ("both", "compare", "comparison", "vs", "versus", "between")
        subject_markers = ("project", "codebase", "repo", "repository", "system", "implementation")
        if not any(marker in prompt for marker in broad_markers):
            return False
        if not any(marker in prompt for marker in compare_markers):
            return False
        if not any(marker in prompt for marker in subject_markers):
            return False

        exploration_tools = {
            "list_dir",
            "read_file",
            "glob_files",
            "grep_files",
            "web_search",
            "web_fetch",
        }
        return bool(tool_calls) and all(tc.name in exploration_tools for tc in tool_calls)

    async def _enforce_parallel_understanding_delegation(
        self,
        tool_calls: list[Any],
        tool_results: list[dict],
    ) -> list[Any]:
        if not self._needs_parallel_understanding_delegation(tool_calls):
            return tool_calls
        auto_tasks = self._build_parallel_understanding_task_pair()
        if auto_tasks is None:
            return tool_calls
        retained = [tc for tc in tool_calls if tc.name not in {"list_dir", "read_file", "glob_files", "grep_files", "web_search", "web_fetch"}]
        return retained + auto_tasks

    def _auto_expand_single_understanding_task(self, tool_calls: list[Any]) -> list[Any] | None:
        targets = self._extract_parallel_understanding_targets()
        if len(targets) != 2:
            return None

        fresh_tasks = [
            tc for tc in tool_calls
            if tc.name == "task" and not str(tc.input.get("task_id", "") or "").strip()
        ]
        if len(fresh_tasks) != 1:
            return None

        original = fresh_tasks[0]
        original_text = (
            f"{original.input.get('description', '')}\n{original.input.get('prompt', '')}"
        ).casefold()
        matching_targets = [target for target in targets if target.casefold() in original_text]
        if len(matching_targets) == 1:
            primary_target = matching_targets[0]
            companion_target = targets[1] if targets[0] == primary_target else targets[0]
        else:
            primary_target = targets[0]
            companion_target = targets[1]

        repaired_original = self._replace_tool_call(
            original,
            input={
                **dict(original.input),
                "subagent_type": "explore",
                "description": str(original.input.get("description") or f"Explore {primary_target}")[:80],
            },
        )
        if primary_target.casefold() not in original_text:
            repaired_original = self._replace_tool_call(
                repaired_original,
                input={
                    **dict(repaired_original.input),
                    "description": f"Explore {primary_target}"[:80],
                },
            )

        companion = self._make_understanding_task_call(
            companion_target,
            workspace_root=Path(getattr(self.session, "cwd", Path("."))),
            in_workspace_hint=False,
        )

        repaired_calls: list[Any] = []
        for tc in tool_calls:
            if tc.id == original.id:
                repaired_calls.append(repaired_original)
            elif tc.name in {"list_dir", "read_file", "glob_files", "grep_files", "web_search", "web_fetch"}:
                continue
            else:
                repaired_calls.append(tc)
        repaired_calls.append(companion)
        return repaired_calls

    async def _prepare_task_batches(
        self,
        tool_calls: list[Any],
        tool_results: list[dict],
    ) -> tuple[list[Any], dict[str, dict[str, int | str]]]:
        fresh_task_calls = [
            tc for tc in tool_calls
            if tc.name == "task" and not str(tc.input.get("task_id", "") or "").strip()
        ]
        if not fresh_task_calls:
            return tool_calls, {}

        if len(fresh_task_calls) == 1:
            repaired_calls = self._auto_expand_single_understanding_task(tool_calls)
            if repaired_calls is not None:
                tool_calls = repaired_calls
                fresh_task_calls = [
                    tc for tc in tool_calls
                    if tc.name == "task" and not str(tc.input.get("task_id", "") or "").strip()
                ]

        if len(fresh_task_calls) == 1:
            tc = fresh_task_calls[0]
            message = (
                "Parallel delegation policy: fresh subagent delegation requires at least 2 task calls in the same response. "
                "Either launch 2 or more distinct subagents in parallel, or stay in the main thread."
            )
            await self.emit(ToolCallStartedEvent(
                type="tool_call_started",
                tool_call_id=tc.id,
                tool_name=tc.name,
                tool_input=tc.input,
            ))
            await self.emit(ToolCallCompletedEvent(
                type="tool_call_completed",
                tool_call_id=tc.id,
                tool_name=tc.name,
                output=message,
                duration_ms=0,
                error=message,
            ))
            tool_results.append({
                "type": "function_call_output",
                "call_id": tc.id,
                "output": message,
            })
            return [call for call in tool_calls if call.id != tc.id], {}

        group_id = uuid.uuid4().hex[:8]
        batches = {
            tc.id: {
                "group_id": group_id,
                "group_size": len(fresh_task_calls),
                "group_index": index + 1,
            }
            for index, tc in enumerate(fresh_task_calls)
        }
        return tool_calls, batches

    async def _execute_single(self, tc: Any, task_batch: dict[str, int | str] | None = None) -> dict | None:
        if self.cancel_event.is_set():
            return None

        call_id = tc.id
        tool_name = tc.name

        await self.emit(ToolCallStartedEvent(
            type="tool_call_started",
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_input=tc.input,
        ))

        caps = self.session.tool_registry.get_tool_capabilities(tool_name)
        if caps.emits_exec_events and tool_name == "shell":
            result_text = await self._execute_shell(call_id, tc.input)
            await self.emit(ToolCallCompletedEvent(
                type="tool_call_completed",
                tool_call_id=call_id,
                tool_name=tool_name,
                output=result_text,
                error=result_text if result_text.startswith("Error:") else None,
            ))
            return {
                "type": "function_call_output",
                "call_id": call_id,
                "output": result_text,
            }

        ctx = await self._build_tool_context()
        ctx.current_tool_call_id = call_id
        ctx.task_batch = dict(task_batch or {})
        t0 = time.monotonic()
        tool_error: str | None = None
        try:
            result_text = await self.session.tool_registry.dispatch(tool_name, tc.input, ctx)
        except Exception as exc:
            result_text = f"Error: {exc}"
            tool_error = result_text
        duration_ms = int((time.monotonic() - t0) * 1000)

        await self.emit(ToolCallCompletedEvent(
            type="tool_call_completed",
            tool_call_id=call_id,
            tool_name=tool_name,
            output=result_text,
            duration_ms=duration_ms,
            error=tool_error,
        ))

        if tool_error is not None:
            from bob.protocol.config_types import HookEventName
            import asyncio as _asyncio
            _asyncio.create_task(self.session.hook_runner.run_hooks(
                HookEventName.POST_TOOL_USE_FAILURE,
                {"tool": tool_name, "error": tool_error, "duration_ms": duration_ms},
            ))

        return {
            "type": "function_call_output",
            "call_id": call_id,
            "output": result_text,
        }

    async def _execute_shell(self, call_id: str, tool_input: dict) -> str:
        raw_cmd = tool_input.get("command", [])
        if isinstance(raw_cmd, str):
            command: list[str] = raw_cmd.split()
        else:
            command = list(raw_cmd)
        command, normalization_reason = self._normalize_windows_shell_command(command)
        if normalization_reason and hasattr(self.session, "_log_action_line"):
            self.session._log_action_line(
                f"[shell] normalized reason={normalization_reason} command={' '.join(command)}"
            )

        exec_cwd = self.session.cwd
        workdir = tool_input.get("workdir")
        if workdir:
            p = Path(workdir)
            exec_cwd = p if p.is_absolute() else self.session.cwd / p

        # apply_patch is routed through Python implementation.
        if command and command[0] == "apply_patch":
            patch_text = command[1] if len(command) > 1 else ""
            if not patch_text:
                return "Error: apply_patch requires patch content"
            from bob.tools.apply_patch import apply_patch_command

            await self.emit(ExecStartedEvent(
                type="exec_started",
                tool_call_id=call_id,
                command=command,
                cwd=str(exec_cwd),
                source=ExecCommandSource.AGENT,
                sandbox_mode=self.session.sandbox_policy.mode,
            ))
            result_text = await apply_patch_command(patch_text, exec_cwd)
            exit_code = 0 if not result_text.startswith("Error") else 1
            await self.emit(ExecCompletedEvent(
                type="exec_completed",
                tool_call_id=call_id,
                exit_code=exit_code,
                status=ExecCommandStatus.COMPLETED if exit_code == 0 else ExecCommandStatus.FAILED,
                duration_ms=0,
            ))
            return result_text

        escalation_reason = self.detect_escalation_fn(command)
        approval_needed = escalation_reason is not None or self.needs_approval_fn(
            command,
            self.session.config.ask_for_approval,
            self.session_approved_commands,
            self.session.config.trusted_commands,
        )
        approval_reason = escalation_reason or "Command requires approval per policy"

        if approval_needed:
            # Fire permission_request hook before prompting the user
            from bob.protocol.config_types import HookEventName
            perm_ctx = {"command": " ".join(command), "cwd": str(exec_cwd), "reason": approval_reason}
            await self.session.hook_runner.run_hooks(HookEventName.PERMISSION_REQUEST, perm_ctx)

            await self.emit(ExecApprovalRequestedEvent(
                type="exec_approval_requested",
                tool_call_id=call_id,
                command=command,
                cwd=str(exec_cwd),
                reason=approval_reason,
                alternatives=[],
            ))
            decision = await self.session.get_approval(call_id)
            await self.emit(ExecApprovalResolvedEvent(
                type="exec_approval_resolved",
                tool_call_id=call_id,
                decision=decision,
            ))
            if decision == ReviewDecision.ABORT:
                await self.emit(TurnInterruptedEvent(
                    type="turn_interrupted", turn_id=self.turn_id, graceful=True
                ))
                raise TurnAbortRequested()
            if decision == ReviewDecision.DENIED:
                from bob.protocol.config_types import HookEventName
                denied_ctx = {"command": " ".join(command), "cwd": str(exec_cwd)}
                import asyncio as _asyncio
                _asyncio.create_task(self.session.hook_runner.run_hooks(
                    HookEventName.PERMISSION_DENIED, denied_ctx
                ))
                return "Command denied by user."
            if decision == ReviewDecision.APPROVED_FOR_SESSION:
                key = " ".join(command[:2])
                self.session_approved_commands.add(key)

        await self.emit(ExecStartedEvent(
            type="exec_started",
            tool_call_id=call_id,
            command=command,
            cwd=str(exec_cwd),
            source=ExecCommandSource.AGENT,
            sandbox_mode=self.session.sandbox_policy.mode,
        ))

        from bob.core.exec import execute_command

        async def on_delta(data: str, stream: str) -> None:
            await self.emit(ExecOutputEvent(
                type="exec_output",
                tool_call_id=call_id,
                stream=stream,
                data=data,
            ))

        timeout_ms: int = tool_input.get("timeout", 10_000)
        try:
            exec_result = await execute_command(
                command=command,
                cwd=exec_cwd,
                sandbox=self.session._sandbox_runner,
                cancel_event=self.cancel_event,
                on_output_delta=on_delta,
                timeout_ms=timeout_ms,
            )
        except Exception as exc:
            result_text = f"Error: {exc}"
            await self.emit(ExecCompletedEvent(
                type="exec_completed",
                tool_call_id=call_id,
                exit_code=1,
                status=ExecCommandStatus.FAILED,
                duration_ms=0,
            ))
            return result_text

        status = ExecCommandStatus.COMPLETED if exec_result.exit_code == 0 else ExecCommandStatus.FAILED
        await self.emit(ExecCompletedEvent(
            type="exec_completed",
            tool_call_id=call_id,
            exit_code=exec_result.exit_code,
            status=status,
            duration_ms=exec_result.duration_ms,
        ))

        result_text = exec_result.aggregated_output or exec_result.stdout
        if exec_result.timed_out:
            result_text = f"[Command timed out]\n{result_text}"
        elif exec_result.exit_code != 0:
            if result_text.strip():
                result_text += f"\n[Exit code: {exec_result.exit_code}]"
            else:
                result_text = f"[Exit code: {exec_result.exit_code}]"

        if (
            exec_result.exit_code != 0
            and self.session.config.ask_for_approval == AskForApproval.ON_FAILURE
        ):
            await self.emit(ExecApprovalRequestedEvent(
                type="exec_approval_requested",
                tool_call_id=call_id,
                command=command,
                cwd=str(exec_cwd),
                reason=f"Command failed with exit code {exec_result.exit_code}",
                alternatives=[],
            ))

        return result_text
