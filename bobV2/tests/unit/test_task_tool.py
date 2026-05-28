from __future__ import annotations

from types import SimpleNamespace

import pytest

from bob.tools.task import task_handler


@pytest.mark.asyncio
async def test_task_handler_blocks_non_explore_in_plan_mode() -> None:
    context = SimpleNamespace(
        _session=SimpleNamespace(
            _plan_mode=True,
            agent_control=SimpleNamespace(),
        )
    )

    result = await task_handler(
        {
            "description": "Plan work",
            "prompt": "Figure out the implementation strategy.",
            "subagent_type": "general",
        },
        context,
    )

    assert result == "Error: Plan mode only allows the explore subagent type."
