from __future__ import annotations

from bob.app_server.errors import not_found
from bob.app_server.routes._utils import parse_params
from bob.protocol.v1.requests import TasksCancelParams, TasksCreateParams, TasksGetParams, TasksListParams


def register(router) -> None:
    async def tasks_create(ctx, params: dict):
        p = parse_params(TasksCreateParams, params)
        task = await ctx.task_runtime.create_task(
            task_type=p.type,
            payload=p.payload,
            priority=p.priority,
            max_attempts=p.max_attempts,
            timeout_seconds=p.timeout_seconds,
            run_at_ts=p.run_at_ts,
        )
        return {"task": task}

    async def tasks_get(ctx, params: dict):
        p = parse_params(TasksGetParams, params)
        task = await ctx.task_runtime.get_task(p.task_id)
        if task is None:
            raise not_found("Task not found", task_id=p.task_id)
        return {"task": task}

    async def tasks_list(ctx, params: dict):
        p = parse_params(TasksListParams, params)
        tasks = await ctx.task_runtime.list_tasks(status=p.status, limit=p.limit)
        return {"tasks": tasks}

    async def tasks_cancel(ctx, params: dict):
        p = parse_params(TasksCancelParams, params)
        ok = await ctx.task_runtime.cancel_task(p.task_id)
        if not ok:
            raise not_found("Task not found or already terminal", task_id=p.task_id)
        return {"status": "ok"}

    router.add("tasks.create", tasks_create)
    router.add("tasks.get", tasks_get)
    router.add("tasks.list", tasks_list)
    router.add("tasks.cancel", tasks_cancel)

