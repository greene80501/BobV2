from __future__ import annotations
import asyncio
import os
import subprocess
from dataclasses import dataclass, field
from typing import Optional
from bob.protocol.config_types import HookEventName, HookRunStatus


@dataclass
class HookConfig:
    """Configuration for a single event hook."""

    event: HookEventName
    command: list[str]
    # "sync" — await result and optionally block; "async" — fire and forget
    mode: str = "sync"
    # timeout in seconds; 0 = no limit
    timeout_seconds: int = 30
    # Extra environment variables injected into the hook process
    extra_env: dict[str, str] = field(default_factory=dict)


@dataclass
class HookResult:
    """Result of executing a single hook."""

    status: HookRunStatus
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    # True when a sync hook returned non-zero and should block the action
    blocked: bool = False


class HookRunner:
    """Executes configured hooks for lifecycle events."""

    def __init__(self, hooks: list[HookConfig]):
        self._hooks = hooks

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_hooks(
        self,
        event: HookEventName,
        context: Optional[dict] = None,
    ) -> list[HookResult]:
        """Run all hooks registered for *event*.

        Sync hooks are awaited sequentially; if any sync hook exits non-zero
        its ``blocked`` flag is True and no further hooks for this event run.

        Async hooks are fired in background tasks and do not contribute to the
        returned list.

        Parameters
        ----------
        event:
            The lifecycle event that just occurred.
        context:
            Optional key-value context injected as ``BOB_<KEY>`` environment
            variables into each hook subprocess.
        """
        matching = [h for h in self._hooks if h.event == event]
        if not matching:
            return []

        results: list[HookResult] = []
        for hook in matching:
            if hook.mode == "async":
                asyncio.create_task(self._execute(hook, context))
            else:
                result = await self._execute(hook, context)
                results.append(result)
                if result.blocked:
                    # A blocking sync hook failed — stop processing further hooks
                    break

        return results

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    async def _execute(
        self,
        hook: HookConfig,
        context: Optional[dict],
    ) -> HookResult:
        env = os.environ.copy()

        # Inject hook extra env
        env.update(hook.extra_env)

        # Inject context as BOB_* environment variables
        if context:
            for key, value in context.items():
                env[f"BOB_{key.upper()}"] = str(value)

        timeout = hook.timeout_seconds if hook.timeout_seconds > 0 else None

        try:
            proc = await asyncio.create_subprocess_exec(
                *hook.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=float(timeout) if timeout else None,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return HookResult(
                    status=HookRunStatus.FAILED,
                    exit_code=-1,
                    stderr=f"Hook timed out after {timeout}s",
                    blocked=hook.mode == "sync",
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = proc.returncode if proc.returncode is not None else -1
            success = exit_code == 0

            return HookResult(
                status=HookRunStatus.COMPLETED if success else HookRunStatus.FAILED,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                blocked=(not success and hook.mode == "sync"),
            )

        except FileNotFoundError:
            return HookResult(
                status=HookRunStatus.FAILED,
                stderr=f"Hook command not found: {hook.command[0]}",
                exit_code=-1,
                blocked=hook.mode == "sync",
            )
        except Exception as exc:
            return HookResult(
                status=HookRunStatus.FAILED,
                stderr=str(exc),
                exit_code=-1,
                blocked=hook.mode == "sync",
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def hooks_for_event(self, event: HookEventName) -> list[HookConfig]:
        return [h for h in self._hooks if h.event == event]

    @property
    def has_hooks(self) -> bool:
        return bool(self._hooks)

    def add_hook(self, hook: HookConfig) -> None:
        self._hooks.append(hook)

    def clear_hooks(self, event: Optional[HookEventName] = None) -> None:
        if event is None:
            self._hooks.clear()
        else:
            self._hooks = [h for h in self._hooks if h.event != event]
