from __future__ import annotations

from bob.app_server.routes._utils import parse_params
from bob.protocol.v1.requests import ExecStartParams, ExecTerminateParams, ExecWaitParams


def register(router) -> None:
    async def exec_start(ctx, params: dict):
        p = parse_params(ExecStartParams, params)
        out = await ctx.task_runtime.start_command(
            thread_id=p.thread_id,
            command=p.command,
            cwd=p.cwd,
        )
        return out

    async def exec_wait(ctx, params: dict):
        p = parse_params(ExecWaitParams, params)
        return await ctx.task_runtime.wait_command(
            thread_id=p.thread_id,
            command_id=p.command_id,
            timeout_ms=p.timeout_ms,
        )

    async def exec_terminate(ctx, params: dict):
        p = parse_params(ExecTerminateParams, params)
        return await ctx.task_runtime.terminate_command(
            thread_id=p.thread_id,
            command_id=p.command_id,
        )

    router.add("exec.start", exec_start)
    router.add("exec.wait", exec_wait)
    router.add("exec.terminate", exec_terminate)

