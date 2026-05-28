import asyncio
from types import SimpleNamespace

from bob.core.tool_orchestrator import ToolOrchestrator


def test_normalize_windows_dir_flags_to_get_child_item() -> None:
    command, reason = ToolOrchestrator._normalize_windows_shell_command(
        ["dir", "/s", "/b", "bobV2"]
    )

    assert reason == "normalized_windows_dir_flags"
    assert command == ["Get-ChildItem", "-Recurse", "-Name", "bobV2"]


def test_normalize_windows_dir_flags_keeps_non_dir_commands() -> None:
    command, reason = ToolOrchestrator._normalize_windows_shell_command(
        ["Get-ChildItem", "-Recurse", "-Name", "bobV2"]
    )

    assert reason is None
    assert command == ["Get-ChildItem", "-Recurse", "-Name", "bobV2"]


def test_prepare_task_batches_rejects_single_fresh_task() -> None:
    async def _run() -> None:
        events: list[object] = []

        async def _emit(msg) -> None:
            events.append(msg)

        orchestrator = ToolOrchestrator(
            session=SimpleNamespace(),
            emit=_emit,
            cancel_event=asyncio.Event(),
            turn_id="turn-1",
            on_output_delta=None,
            on_plan_update=None,
            session_approved_commands=set(),
            needs_approval_fn=lambda *_args, **_kwargs: False,
            detect_escalation_fn=lambda _cmd: None,
        )
        tool_results: list[dict] = []
        calls = [
            SimpleNamespace(
                id="call-1",
                name="task",
                input={"description": "Bob", "prompt": "Explore Bob", "subagent_type": "explore"},
            )
        ]

        filtered, batches = await orchestrator._prepare_task_batches(calls, tool_results)

        assert filtered == []
        assert batches == {}
        assert len(tool_results) == 1
        assert "requires at least 2 task calls" in tool_results[0]["output"]
        assert len(events) == 2

    asyncio.run(_run())


def test_prepare_task_batches_groups_parallel_fresh_tasks() -> None:
    async def _run() -> None:
        async def _emit(_msg) -> None:
            return None

        orchestrator = ToolOrchestrator(
            session=SimpleNamespace(),
            emit=_emit,
            cancel_event=asyncio.Event(),
            turn_id="turn-1",
            on_output_delta=None,
            on_plan_update=None,
            session_approved_commands=set(),
            needs_approval_fn=lambda *_args, **_kwargs: False,
            detect_escalation_fn=lambda _cmd: None,
        )
        tool_results: list[dict] = []
        calls = [
            SimpleNamespace(
                id="call-1",
                name="task",
                input={"description": "Bob", "prompt": "Explore Bob", "subagent_type": "explore"},
            ),
            SimpleNamespace(
                id="call-2",
                name="task",
                input={"description": "OpenCode", "prompt": "Explore OpenCode", "subagent_type": "explore"},
            ),
        ]

        filtered, batches = await orchestrator._prepare_task_batches(calls, tool_results)

        assert filtered == calls
        assert tool_results == []
        assert batches["call-1"]["group_size"] == 2
        assert batches["call-2"]["group_size"] == 2
        assert batches["call-1"]["group_id"] == batches["call-2"]["group_id"]
        assert batches["call-1"]["group_index"] == 1
        assert batches["call-2"]["group_index"] == 2

    asyncio.run(_run())


def test_understanding_delegation_detects_two_project_comparison_prompt() -> None:
    orchestrator = ToolOrchestrator(
        session=SimpleNamespace(_current_prompt_text="Get a full understanding for both the Bob V2 Project and OpenCode Project."),
        emit=None,
        cancel_event=asyncio.Event(),
        turn_id="turn-1",
        on_output_delta=None,
        on_plan_update=None,
        session_approved_commands=set(),
        needs_approval_fn=lambda *_args, **_kwargs: False,
        detect_escalation_fn=lambda _cmd: None,
    )

    calls = [
        SimpleNamespace(id="call-1", name="list_dir", input={"path": "bob"}),
        SimpleNamespace(id="call-2", name="read_file", input={"path": "README.md"}),
    ]

    assert orchestrator._needs_parallel_understanding_delegation(calls) is True


def test_understanding_delegation_ignores_prompts_that_already_delegate() -> None:
    orchestrator = ToolOrchestrator(
        session=SimpleNamespace(_current_prompt_text="Compare both codebases and summarize them."),
        emit=None,
        cancel_event=asyncio.Event(),
        turn_id="turn-1",
        on_output_delta=None,
        on_plan_update=None,
        session_approved_commands=set(),
        needs_approval_fn=lambda *_args, **_kwargs: False,
        detect_escalation_fn=lambda _cmd: None,
    )

    calls = [
        SimpleNamespace(
            id="call-1",
            name="task",
            input={"description": "Bob", "prompt": "Explore Bob", "subagent_type": "explore"},
        ),
        SimpleNamespace(
            id="call-2",
            name="task",
            input={"description": "OpenCode", "prompt": "Explore OpenCode", "subagent_type": "explore"},
        ),
    ]

    assert orchestrator._needs_parallel_understanding_delegation(calls) is False


def test_prepare_task_batches_auto_expands_single_understanding_task() -> None:
    async def _run() -> None:
        async def _emit(_msg) -> None:
            return None

        orchestrator = ToolOrchestrator(
            session=SimpleNamespace(
                _current_prompt_text="Get a full understanding for both the Bob V2 Project and OpenCode Project."
            ),
            emit=_emit,
            cancel_event=asyncio.Event(),
            turn_id="turn-1",
            on_output_delta=None,
            on_plan_update=None,
            session_approved_commands=set(),
            needs_approval_fn=lambda *_args, **_kwargs: False,
            detect_escalation_fn=lambda _cmd: None,
        )
        tool_results: list[dict] = []
        calls = [
            SimpleNamespace(
                id="call-1",
                name="task",
                input={"description": "Explore Bob V2 codebase", "prompt": "Explore Bob V2 deeply", "subagent_type": "explore"},
            )
        ]

        filtered, batches = await orchestrator._prepare_task_batches(calls, tool_results)

        assert tool_results == []
        assert len(filtered) == 2
        assert sum(1 for call in filtered if call.name == "task") == 2
        descriptions = [call.input["description"] for call in filtered]
        assert any("Bob V2" in desc for desc in descriptions)
        assert any("OpenCode" in desc for desc in descriptions)
        assert len(batches) == 2

    asyncio.run(_run())


def test_understanding_delegation_rewrites_exploration_batch_to_two_tasks() -> None:
    async def _run() -> None:
        orchestrator = ToolOrchestrator(
            session=SimpleNamespace(
                _current_prompt_text="Get a full understanding for both the Bob V2 Project and OpenCode Project.",
                cwd="C:\\Users\\green\\Bob_V2_SubAgent_sys\\BobV2\\bobV2",
            ),
            emit=lambda _msg: asyncio.sleep(0),
            cancel_event=asyncio.Event(),
            turn_id="turn-1",
            on_output_delta=None,
            on_plan_update=None,
            session_approved_commands=set(),
            needs_approval_fn=lambda *_args, **_kwargs: False,
            detect_escalation_fn=lambda _cmd: None,
        )
        tool_results: list[dict] = []
        calls = [
            SimpleNamespace(id="call-1", name="glob_files", input={"pattern": "**/*opencode*"}),
        ]

        rewritten = await orchestrator._enforce_parallel_understanding_delegation(calls, tool_results)

        assert tool_results == []
        assert len(rewritten) == 2
        assert all(call.name == "task" for call in rewritten)
        descriptions = [call.input["description"] for call in rewritten]
        assert any("Bob V2" in desc for desc in descriptions)
        assert any("OpenCode" in desc for desc in descriptions)

    asyncio.run(_run())
