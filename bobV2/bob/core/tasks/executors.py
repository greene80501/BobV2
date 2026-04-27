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


class SshExecutor(BaseExecutor):
    kind = "remote_shell"

    async def execute(self, payload: dict[str, Any], runtime: Any) -> ExecutionResult:
        return ExecutionResult(
            ok=False,
            result={"capability": "ssh_executor"},
            error="SshExecutor is scaffolded but not enabled yet",
        )
