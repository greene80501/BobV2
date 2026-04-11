from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass
class ExecutionResult:
    ok: bool
    result: dict[str, Any]
    error: str | None = None


class BaseExecutor:
    kind = "base"

    async def execute(self, payload: dict[str, Any], runtime: Any) -> ExecutionResult:
        raise NotImplementedError


class LocalExecutor(BaseExecutor):
    kind = "local_shell"

    async def execute(self, payload: dict[str, Any], runtime: Any) -> ExecutionResult:
        command = str(payload.get("command", "")).strip()
        cwd = payload.get("cwd")
        if not command:
            return ExecutionResult(ok=False, result={}, error="Missing command")

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return ExecutionResult(
            ok=proc.returncode == 0,
            result={
                "command": command,
                "exit_code": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            },
            error=None if proc.returncode == 0 else f"Command exited with {proc.returncode}",
        )


class LocalAgentExecutor(BaseExecutor):
    kind = "local_agent"

    async def execute(self, payload: dict[str, Any], runtime: Any) -> ExecutionResult:
        thread_id = str(payload.get("thread_id", ""))
        task = str(payload.get("task", ""))
        if not thread_id or not task:
            return ExecutionResult(ok=False, result={}, error="thread_id and task are required")
        thread = await runtime.registry.get_thread(thread_id)
        if thread is None:
            return ExecutionResult(ok=False, result={}, error=f"Thread not found: {thread_id}")

        agent_id = await runtime.agent_runtime.manager.spawn(
            session=thread.session,
            task=task,
            mode=str(payload.get("mode", "default")),
            model=payload.get("model"),
            cwd=payload.get("cwd"),
            name=payload.get("name"),
        )
        result = await runtime.agent_runtime.manager.wait(
            session=thread.session,
            agent_id=agent_id,
            timeout_seconds=payload.get("timeout_seconds"),
        )
        return ExecutionResult(ok=result is not None, result={"agent_id": agent_id, "result": result})


class SshExecutor(BaseExecutor):
    kind = "remote_shell"

    async def execute(self, payload: dict[str, Any], runtime: Any) -> ExecutionResult:
        return ExecutionResult(
            ok=False,
            result={"capability": "ssh_executor"},
            error="SshExecutor is scaffolded but not enabled yet",
        )


class ContainerExecutor(BaseExecutor):
    kind = "remote_agent"

    async def execute(self, payload: dict[str, Any], runtime: Any) -> ExecutionResult:
        return ExecutionResult(
            ok=False,
            result={"capability": "container_executor"},
            error="ContainerExecutor is scaffolded but not enabled yet",
        )

