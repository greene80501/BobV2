from __future__ import annotations
import asyncio
import uuid
import os
from pathlib import Path
from typing import Optional, AsyncIterator, Any
from bob.config.schema import BobConfig
from bob.protocol.config_types import SandboxPolicy, SandboxMode, AskForApproval
from bob.protocol.ops import (
    Op, Submission, UserTurnOp, InterruptOp, CompactOp, ShutdownOp,
    SetThreadNameOp, RunUserShellCommandOp,
)
from bob.protocol.events import Event, EventMsg


class ToolContext:
    """Passed to tool handlers — contains session state they need."""

    def __init__(self, session: "BobSession"):
        self.cwd = session.cwd
        self.sandbox = session._sandbox_runner
        self.cancel_event = session._cancel_event
        self.approval_policy = session.config.ask_for_approval
        self.thread_manager = None   # set per-turn for multi-agent
        self.on_output_delta = None  # set per-turn
        self.on_plan_update = None   # set per-turn
        self.on_request_user_input = None
        # Back-reference so plan_mode tools can toggle the flag
        self._session = session


class BobSession:
    """
    Core session: submission queue + event queue + agent loop.

    All communication is async:
    - submit(op) -> enqueues an Op
    - events()   -> async iterator of Events
    """

    def __init__(self, config: BobConfig, cwd: Path, ephemeral: bool = False):
        self.config = config
        self.cwd = cwd.resolve()
        self.ephemeral = ephemeral
        self.session_id = str(uuid.uuid4())

        self._sq: asyncio.Queue[Submission] = asyncio.Queue()
        self._eq: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
        self._cancel_event: asyncio.Event = asyncio.Event()
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._agent_task: Optional[asyncio.Task] = None
        self._current_turn_cancel: Optional[asyncio.Event] = None
        self._pending_approvals: dict[str, asyncio.Future] = {}

        # Scratch attributes set per-turn so tool context can read them
        self._current_on_output_delta = None
        self._current_on_plan_update = None

        # Setup sandbox
        sandbox_policy = SandboxPolicy(
            mode=config.sandbox_mode,
            network_access=config.network_access,
            cwd=self.cwd,
        )
        self.sandbox_policy = sandbox_policy

        from bob.sandbox import get_sandbox_runner
        self._sandbox_runner = get_sandbox_runner(sandbox_policy, self.cwd)

        # Context manager for conversation history
        from bob.core.context_manager import ContextManager
        self.context_manager = ContextManager()

        # Resolve API key: prefer config.api_key, then common env vars.
        api_key = (
            config.api_key
            or os.environ.get("OPENAI_API_KEY", "")
            or os.environ.get("ANTHROPIC_API_KEY", "")
            or os.environ.get("BOB_API_KEY", "")
        )
        self._api_key = api_key
        self.client = self._make_client(config.model)

        # Analytics: per-turn token/cost/latency tracking
        from bob.analytics.db import AnalyticsDB
        from bob.analytics.tracker import AnalyticsTracker
        from bob.llm.catalog import get_catalog
        self._analytics_db = AnalyticsDB(self.bob_home / "analytics.db")
        self.analytics = AnalyticsTracker(self._analytics_db, get_catalog())

        # Tool registry
        from bob.tools.registry import ToolRegistry
        self.tool_registry = ToolRegistry()
        self._register_builtin_tools()

        # Plan mode: when True, write tools are filtered out of tool specs
        self._plan_mode: bool = False

        # Multi-agent thread manager (lazy)
        self._thread_manager = None

        # Pending user-input futures keyed by request_id
        self._pending_user_inputs: dict[str, asyncio.Future] = {}

        # Persistence handles — populated in _setup_persistence
        self._recorder = None
        self._state_db = None
        self._session_index = None

        # System prompt cache
        self._system_prompt: Optional[str] = None

    # ------------------------------------------------------------------
    # Bob home helper
    # ------------------------------------------------------------------

    @property
    def bob_home(self) -> Path:
        """Return the ~/.bob directory (or $BOB_HOME if set)."""
        return Path(os.environ.get("BOB_HOME", Path.home() / ".bob"))

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_builtin_tools(self) -> None:
        from bob.tools.shell import (
            shell_handler, SHELL_TOOL_DESCRIPTION, SHELL_TOOL_SCHEMA,
        )
        from bob.tools.update_plan import (
            update_plan_handler, UPDATE_PLAN_DESCRIPTION, UPDATE_PLAN_SCHEMA,
        )
        from bob.tools.view_image import (
            view_image_handler, VIEW_IMAGE_DESCRIPTION, VIEW_IMAGE_SCHEMA,
        )
        from bob.tools.list_dir import (
            list_dir_handler, LIST_DIR_DESCRIPTION, LIST_DIR_SCHEMA,
        )
        from bob.tools.read_file import (
            read_file_handler, READ_FILE_DESCRIPTION, READ_FILE_SCHEMA,
        )
        from bob.tools.write_file import (
            write_file_handler, WRITE_FILE_DESCRIPTION, WRITE_FILE_SCHEMA,
        )
        from bob.tools.edit_file import (
            edit_file_handler, EDIT_FILE_DESCRIPTION, EDIT_FILE_SCHEMA,
        )
        from bob.tools.glob_files import (
            glob_files_handler, GLOB_FILES_DESCRIPTION, GLOB_FILES_SCHEMA,
        )
        from bob.tools.grep_files import (
            grep_files_handler, GREP_FILES_DESCRIPTION, GREP_FILES_SCHEMA,
        )
        from bob.tools.sleep_tool import (
            sleep_handler, SLEEP_DESCRIPTION, SLEEP_SCHEMA,
        )
        from bob.tools.todo_write import (
            todo_write_handler, TODO_WRITE_DESCRIPTION, TODO_WRITE_SCHEMA,
        )
        from bob.tools.plan_mode import (
            enter_plan_mode_handler, ENTER_PLAN_MODE_DESCRIPTION, ENTER_PLAN_MODE_SCHEMA,
            exit_plan_mode_handler, EXIT_PLAN_MODE_DESCRIPTION, EXIT_PLAN_MODE_SCHEMA,
        )
        from bob.tools.web_fetch import (
            web_fetch_handler, WEB_FETCH_DESCRIPTION, WEB_FETCH_SCHEMA,
        )
        from bob.tools.web_search import (
            web_search_handler, WEB_SEARCH_DESCRIPTION, WEB_SEARCH_SCHEMA,
        )
        from bob.tools.js_repl import (
            js_repl_handler, JS_REPL_DESCRIPTION, JS_REPL_SCHEMA,
        )
        from bob.tools.notebook_read import (
            notebook_read_handler, NOTEBOOK_READ_DESCRIPTION, NOTEBOOK_READ_SCHEMA,
        )
        from bob.tools.notebook_edit import (
            notebook_edit_handler, NOTEBOOK_EDIT_DESCRIPTION, NOTEBOOK_EDIT_SCHEMA,
        )
        from bob.tools.multi_agent.spawn_agent import (
            spawn_agent_handler, SPAWN_AGENT_DESCRIPTION, SPAWN_AGENT_SCHEMA,
        )
        from bob.tools.multi_agent.send_message import (
            send_message_handler, SEND_MESSAGE_DESCRIPTION, SEND_MESSAGE_SCHEMA,
        )
        from bob.tools.multi_agent.wait_agent import (
            wait_agent_handler, WAIT_AGENT_DESCRIPTION, WAIT_AGENT_SCHEMA,
        )
        from bob.tools.multi_agent.list_agents import (
            list_agents_handler, LIST_AGENTS_DESCRIPTION, LIST_AGENTS_SCHEMA,
        )
        from bob.tools.multi_agent.close_agent import (
            close_agent_handler, CLOSE_AGENT_DESCRIPTION, CLOSE_AGENT_SCHEMA,
        )

        # Core tools
        self.tool_registry.register(
            "shell", SHELL_TOOL_DESCRIPTION, SHELL_TOOL_SCHEMA, shell_handler
        )
        self.tool_registry.register(
            "update_plan", UPDATE_PLAN_DESCRIPTION, UPDATE_PLAN_SCHEMA, update_plan_handler
        )
        self.tool_registry.register(
            "view_image", VIEW_IMAGE_DESCRIPTION, VIEW_IMAGE_SCHEMA, view_image_handler
        )
        self.tool_registry.register(
            "list_dir", LIST_DIR_DESCRIPTION, LIST_DIR_SCHEMA, list_dir_handler
        )
        # Phase 1 — file tools
        self.tool_registry.register(
            "read_file", READ_FILE_DESCRIPTION, READ_FILE_SCHEMA, read_file_handler
        )
        self.tool_registry.register(
            "write_file", WRITE_FILE_DESCRIPTION, WRITE_FILE_SCHEMA, write_file_handler
        )
        self.tool_registry.register(
            "edit_file", EDIT_FILE_DESCRIPTION, EDIT_FILE_SCHEMA, edit_file_handler
        )
        self.tool_registry.register(
            "glob_files", GLOB_FILES_DESCRIPTION, GLOB_FILES_SCHEMA, glob_files_handler
        )
        self.tool_registry.register(
            "grep_files", GREP_FILES_DESCRIPTION, GREP_FILES_SCHEMA, grep_files_handler
        )
        # Phase 2 — utilities
        self.tool_registry.register(
            "sleep", SLEEP_DESCRIPTION, SLEEP_SCHEMA, sleep_handler
        )
        self.tool_registry.register(
            "todo_write", TODO_WRITE_DESCRIPTION, TODO_WRITE_SCHEMA, todo_write_handler
        )
        self.tool_registry.register(
            "enter_plan_mode", ENTER_PLAN_MODE_DESCRIPTION, ENTER_PLAN_MODE_SCHEMA,
            enter_plan_mode_handler
        )
        self.tool_registry.register(
            "exit_plan_mode", EXIT_PLAN_MODE_DESCRIPTION, EXIT_PLAN_MODE_SCHEMA,
            exit_plan_mode_handler
        )
        self.tool_registry.register(
            "web_fetch", WEB_FETCH_DESCRIPTION, WEB_FETCH_SCHEMA, web_fetch_handler
        )
        self.tool_registry.register(
            "web_search", WEB_SEARCH_DESCRIPTION, WEB_SEARCH_SCHEMA, web_search_handler
        )
        # Phase 5 — advanced
        self.tool_registry.register(
            "js_repl", JS_REPL_DESCRIPTION, JS_REPL_SCHEMA, js_repl_handler
        )
        self.tool_registry.register(
            "notebook_read", NOTEBOOK_READ_DESCRIPTION, NOTEBOOK_READ_SCHEMA, notebook_read_handler
        )
        self.tool_registry.register(
            "notebook_edit", NOTEBOOK_EDIT_DESCRIPTION, NOTEBOOK_EDIT_SCHEMA, notebook_edit_handler
        )
        # Phase 4 — multi-agent
        self.tool_registry.register(
            "spawn_agent", SPAWN_AGENT_DESCRIPTION, SPAWN_AGENT_SCHEMA, spawn_agent_handler
        )
        self.tool_registry.register(
            "send_message", SEND_MESSAGE_DESCRIPTION, SEND_MESSAGE_SCHEMA, send_message_handler
        )
        self.tool_registry.register(
            "wait_agent", WAIT_AGENT_DESCRIPTION, WAIT_AGENT_SCHEMA, wait_agent_handler
        )
        self.tool_registry.register(
            "list_agents", LIST_AGENTS_DESCRIPTION, LIST_AGENTS_SCHEMA, list_agents_handler
        )
        self.tool_registry.register(
            "close_agent", CLOSE_AGENT_DESCRIPTION, CLOSE_AGENT_SCHEMA, close_agent_handler
        )

    def ensure_thread_manager(self):
        """Lazily create and cache the ThreadManager."""
        if self._thread_manager is None:
            from bob.core.thread_manager import ThreadManager
            self._thread_manager = ThreadManager(self)
        return self._thread_manager

    async def request_user_input(self, request_id: str, prompt: str, fields: list) -> str:
        """Called by ask_user tool — creates a future and waits for UserInputAnswerOp."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending_user_inputs[request_id] = fut
        # Emit a UserInputRequestEvent so the TUI can prompt the user
        from bob.protocol.events import UserInputRequestEvent
        await self._emit(Event(
            id=request_id,
            msg=UserInputRequestEvent(
                type="user_input_request",
                request_id=request_id,
                prompt=prompt,
                fields=fields,
            )
        ))
        try:
            return await fut
        finally:
            self._pending_user_inputs.pop(request_id, None)

    # ------------------------------------------------------------------
    # Client factory — routes by model to Responses API or LiteLLM
    # ------------------------------------------------------------------

    # Models that only work with OpenAI's Responses API (not Chat Completions).
    # LiteLLM routes to /v1/chat/completions; these must go through BobClient.
    _RESPONSES_API_MODELS: frozenset[str] = frozenset({
        "gpt-5.1-codex-mini",
        "codex-mini-latest",
    })

    def _make_client(self, model: str):
        """Return BobClient for Responses-API-only models, LiteLLMClient for everything else."""
        bare = model.split("/")[-1]  # strip provider prefix e.g. "openai/gpt-4o" → "gpt-4o"
        if bare in self._RESPONSES_API_MODELS or model in self._RESPONSES_API_MODELS:
            from bob.client.openai_client import BobClient
            kwargs: dict = {"api_key": self._api_key, "model": bare}
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            return BobClient(**kwargs)
        from bob.llm.client import LiteLLMClient
        return LiteLLMClient(
            api_key=self._api_key,
            model=model,
            base_url=self.config.base_url if self.config.base_url else None,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize the session and start the agent loop."""
        await self._setup_persistence()
        await self._analytics_db.setup()
        await self._load_system_prompt()
        self._agent_task = asyncio.create_task(self._agent_loop())

        from bob.protocol.events import SessionStartedEvent
        from bob.protocol.config_types import SessionSource
        await self._emit(Event(
            id="session",
            msg=SessionStartedEvent(
                type="session_started",
                session_id=self.session_id,
                thread_id=self.session_id,
                source=SessionSource.LOCAL,
                model=self.config.model,
                cwd=str(self.cwd),
            )
        ))

    async def _setup_persistence(self) -> None:
        if self.ephemeral:
            return

        bob_home = self.bob_home
        bob_home.mkdir(parents=True, exist_ok=True)

        sessions_dir = bob_home / "sessions"
        sessions_dir.mkdir(exist_ok=True)

        from bob.rollout.state_db import StateDb
        from bob.rollout.session_index import SessionIndex
        from bob.rollout.recorder import RolloutRecorder
        import datetime

        db_path = bob_home / "state.sqlite"
        self._state_db = StateDb(db_path)
        await self._state_db.connect()
        self._session_index = SessionIndex(self._state_db)

        ts = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        rollout_path = sessions_dir / f"{ts}-{self.session_id[:8]}.jsonl"

        self._recorder = RolloutRecorder(
            path=rollout_path,
            session_id=self.session_id,
            model=self.config.model,
            cwd=str(self.cwd),
        )
        await self._recorder.start()

        await self._state_db.upsert_thread(
            id=self.session_id,
            name=None,
            path=str(rollout_path),
            model=self.config.model,
            cwd=str(self.cwd),
        )

    async def _load_system_prompt(self) -> None:
        from bob.prompts import load_system_prompt
        from bob.instructions.loader import load_agents_md
        from bob.core.environment_context import EnvironmentContext

        base = load_system_prompt()

        if self.config.include_agents_md:
            agents_md = load_agents_md(self.cwd, self.bob_home)
            if agents_md:
                base += f"\n\n# Project Instructions (AGENTS.md)\n\n{agents_md}"

        if self.config.developer_instructions:
            base += f"\n\n# Developer Instructions\n\n{self.config.developer_instructions}"

        if self.config.developer_instructions_file:
            try:
                extra = Path(self.config.developer_instructions_file).read_text(encoding="utf-8")
                base += f"\n\n# Developer Instructions File\n\n{extra}"
            except OSError:
                pass

        env_ctx = EnvironmentContext.build(self.cwd)
        base += f"\n\n# Environment\n\n{env_ctx.to_prompt_text()}"

        self._system_prompt = base

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit(self, op: Op) -> str:
        sub = Submission(op=op)
        await self._sq.put(sub)
        return sub.id

    async def events(self) -> AsyncIterator[Event]:
        while not self._shutdown_event.is_set():
            try:
                event = await asyncio.wait_for(self._eq.get(), timeout=0.1)
                yield event
                if hasattr(event.msg, "type") and event.msg.type == "session_ended":
                    break
            except asyncio.TimeoutError:
                continue

    async def _emit(self, event: Event) -> None:
        try:
            self._eq.put_nowait(event)
        except asyncio.QueueFull:
            await self._eq.put(event)

        if self._recorder:
            await self._recorder.write({
                "type": event.msg.type if hasattr(event.msg, "type") else "event",
                "data": event.msg.model_dump(),
            })

    async def interrupt(self) -> None:
        if self._current_turn_cancel:
            self._current_turn_cancel.set()

    async def reset(self) -> None:
        """Start a new conversation (clear history, keep session alive)."""
        self.context_manager.replace([])
        self.session_id = str(uuid.uuid4())
        await self._load_system_prompt()

    async def resume(self, path: str) -> None:
        """Load history from a rollout file."""
        from bob.rollout.recorder import load_rollout
        from bob.core.rollout_reconstruction import reconstruct_history

        items = await load_rollout(Path(path))
        result = reconstruct_history(items)
        self.context_manager.replace(result.history)
        if result.previous_model:
            self.config = self.config.model_copy(update={"model": result.previous_model})

    async def resume_by_id(self, session_id: str) -> None:
        if self._session_index:
            record = await self._session_index.find_by_id(session_id)
            if record and record.path:
                await self.resume(record.path)

    async def fork(self, path: str) -> None:
        """Fork from an existing session's history, creating a new session_id."""
        await self.resume(path)
        self.session_id = str(uuid.uuid4())

    async def list_sessions(self):
        if self._session_index:
            return await self._session_index.list_sessions()
        return []

    async def submit_compact(self) -> None:
        await self.submit(CompactOp(type="compact"))

    async def submit_set_name(self, name: str) -> None:
        await self.submit(SetThreadNameOp(type="set_thread_name", name=name))

    async def shutdown(self) -> None:
        self._shutdown_event.set()
        if self._agent_task:
            self._agent_task.cancel()
            try:
                await asyncio.wait_for(self._agent_task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        if self._recorder:
            await self._recorder.stop()
        if self._state_db:
            await self._state_db.close()

        from bob.protocol.events import SessionEndedEvent
        try:
            self._eq.put_nowait(Event(
                id="session",
                msg=SessionEndedEvent(
                    type="session_ended",
                    session_id=self.session_id,
                    reason="shutdown",
                    exit_code=0,
                )
            ))
        except asyncio.QueueFull:
            pass

    async def get_approval(self, call_id: str) -> Any:
        """Create a future that resolves when an ExecApprovalOp or PatchApprovalOp arrives."""
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._pending_approvals[call_id] = fut
        try:
            return await fut
        finally:
            self._pending_approvals.pop(call_id, None)

    # ------------------------------------------------------------------
    # Agent loop
    # ------------------------------------------------------------------

    async def _agent_loop(self) -> None:
        """Main agent loop: process submissions, run turns, route approval ops."""
        from bob.core.turn import run_turn
        from bob.protocol.ops import (
            UserTurnOp, InterruptOp, ExecApprovalOp, PatchApprovalOp,
            CompactOp, ShutdownOp, SetThreadNameOp, RunUserShellCommandOp,
            OverrideTurnContextOp, ThreadRollbackOp, UndoOp,
            DropMemoriesOp, UpdateMemoriesOp,
        )
        from bob.protocol.events import (
            SessionEndedEvent, WarningEvent, ThreadNameSetEvent,
            HistoryCompactedEvent, UndoCompletedEvent, ThreadRollbackCompletedEvent,
        )

        current_turn_task: Optional[asyncio.Task] = None

        while not self._shutdown_event.is_set():
            try:
                submission = await asyncio.wait_for(self._sq.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            op = submission.op
            sub_id = submission.id

            # ----------------------------------------------------------------
            # Shutdown
            # ----------------------------------------------------------------
            if isinstance(op, ShutdownOp):
                await self._emit(Event(
                    id=sub_id,
                    msg=SessionEndedEvent(
                        type="session_ended",
                        session_id=self.session_id,
                        reason=op.reason or "shutdown",
                        exit_code=op.exit_code,
                    )
                ))
                self._shutdown_event.set()
                break

            # ----------------------------------------------------------------
            # Interrupt
            # ----------------------------------------------------------------
            if isinstance(op, InterruptOp):
                if current_turn_task and not current_turn_task.done():
                    if self._current_turn_cancel:
                        self._current_turn_cancel.set()
                continue

            # ----------------------------------------------------------------
            # Approval resolution
            # ----------------------------------------------------------------
            if isinstance(op, ExecApprovalOp):
                fut = self._pending_approvals.get(op.tool_call_id)
                if fut and not fut.done():
                    fut.set_result(op.decision)
                continue

            if isinstance(op, PatchApprovalOp):
                fut = self._pending_approvals.get(op.tool_call_id)
                if fut and not fut.done():
                    fut.set_result(op.decision)
                continue

            # ----------------------------------------------------------------
            # User input answer (from ask_user tool)
            # ----------------------------------------------------------------
            from bob.protocol.ops import UserInputAnswerOp
            if isinstance(op, UserInputAnswerOp):
                fut = self._pending_user_inputs.get(op.request_id)
                if fut and not fut.done():
                    fut.set_result(op.answer)
                continue

            # ----------------------------------------------------------------
            # Compact
            # ----------------------------------------------------------------
            if isinstance(op, CompactOp):
                from bob.core.compact import run_compact
                summary = await run_compact(self)
                if summary:
                    await self._emit(Event(
                        id=sub_id,
                        msg=HistoryCompactedEvent(
                            type="history_compacted",
                            summary=summary[:500],
                            turns_removed=0,
                        )
                    ))
                    await self._emit(Event(
                        id=sub_id,
                        msg=WarningEvent(
                            type="warning",
                            message=(
                                "Heads up: Long threads and multiple compactions can cause "
                                "the model to be less accurate. Start a new thread when possible."
                            )
                        )
                    ))
                continue

            # ----------------------------------------------------------------
            # Set thread name
            # ----------------------------------------------------------------
            if isinstance(op, SetThreadNameOp):
                if self._state_db:
                    await self._state_db.update_thread_name(self.session_id, op.name)
                await self._emit(Event(
                    id=sub_id,
                    msg=ThreadNameSetEvent(type="thread_name_set", name=op.name)
                ))
                continue

            # ----------------------------------------------------------------
            # Override turn context
            # ----------------------------------------------------------------
            if isinstance(op, OverrideTurnContextOp):
                if op.model:
                    self.config = self.config.model_copy(update={"model": op.model})
                    self.client = self._make_client(op.model)
                if op.sandbox_policy:
                    self.sandbox_policy = op.sandbox_policy
                    from bob.sandbox import get_sandbox_runner
                    self._sandbox_runner = get_sandbox_runner(op.sandbox_policy, self.cwd)
                continue

            # ----------------------------------------------------------------
            # Undo
            # ----------------------------------------------------------------
            if isinstance(op, UndoOp):
                n = max(1, op.turns)
                self.context_manager.drop_last_n_user_turns(n)
                await self._emit(Event(
                    id=sub_id,
                    msg=UndoCompletedEvent(type="undo_completed", turns_removed=n)
                ))
                continue

            # ----------------------------------------------------------------
            # Thread rollback
            # ----------------------------------------------------------------
            if isinstance(op, ThreadRollbackOp):
                # Rolling back to a specific submission id is best-effort;
                # we do a single-turn undo as a safe approximation when we
                # don't have per-submission snapshots.
                self.context_manager.drop_last_n_user_turns(1)
                await self._emit(Event(
                    id=sub_id,
                    msg=ThreadRollbackCompletedEvent(
                        type="thread_rollback_completed",
                        to_submission_id=op.to_submission_id,
                    )
                ))
                continue

            # ----------------------------------------------------------------
            # Drop memories
            # ----------------------------------------------------------------
            if isinstance(op, DropMemoriesOp):
                from bob.protocol.events import MemoriesDroppedEvent
                await self._emit(Event(
                    id=sub_id,
                    msg=MemoriesDroppedEvent(
                        type="memories_dropped",
                        memory_ids=op.memory_ids,
                    )
                ))
                continue

            # ----------------------------------------------------------------
            # Update memories
            # ----------------------------------------------------------------
            if isinstance(op, UpdateMemoriesOp):
                from bob.protocol.events import MemoriesUpdatedEvent
                await self._emit(Event(
                    id=sub_id,
                    msg=MemoriesUpdatedEvent(
                        type="memories_updated",
                        memories=[u.model_dump() for u in op.updates],
                    )
                ))
                continue

            # ----------------------------------------------------------------
            # Run user shell command (outside of an agent turn)
            # ----------------------------------------------------------------
            if isinstance(op, RunUserShellCommandOp):
                import shlex
                cmd_parts = shlex.split(op.command)
                call_id = str(uuid.uuid4())
                cwd = Path(op.cwd).resolve() if op.cwd else self.cwd

                from bob.protocol.events import (
                    ExecStartedEvent, ExecOutputEvent, ExecCompletedEvent,
                )
                from bob.protocol.config_types import ExecCommandSource, ExecCommandStatus

                await self._emit(Event(id=sub_id, msg=ExecStartedEvent(
                    type="exec_started",
                    tool_call_id=call_id,
                    command=cmd_parts,
                    cwd=str(cwd),
                    source=ExecCommandSource.USER_SHELL,
                    sandbox_mode=self.sandbox_policy.mode,
                )))

                exec_result = await self._run_shell_direct(
                    cmd_parts, cwd, sub_id, call_id
                )

                status = (
                    ExecCommandStatus.COMPLETED
                    if exec_result.exit_code == 0
                    else ExecCommandStatus.FAILED
                )
                await self._emit(Event(id=sub_id, msg=ExecCompletedEvent(
                    type="exec_completed",
                    tool_call_id=call_id,
                    exit_code=exec_result.exit_code,
                    status=status,
                    duration_ms=exec_result.duration_ms,
                )))
                continue

            # ----------------------------------------------------------------
            # User turn — the main path
            # ----------------------------------------------------------------
            if isinstance(op, UserTurnOp):
                # Auto-compact when context grows too large
                token_count = self.context_manager.approx_token_count()
                threshold = self.config.auto_compact_threshold_tokens
                if threshold and token_count > threshold:
                    from bob.core.compact import run_compact
                    await run_compact(self)
                elif token_count > 150_000:
                    from bob.core.compact import run_compact
                    await run_compact(self)

                cancel_ev = asyncio.Event()
                self._current_turn_cancel = cancel_ev

                current_turn_task = asyncio.create_task(
                    run_turn(self, sub_id, op, cancel_ev)
                )

                # IMPORTANT: Do NOT await the turn task directly — that would
                # block the loop and create a deadlock when an approval future
                # is waiting for an ExecApprovalOp to arrive in the queue.
                # Instead, poll the queue while the turn is running so we can
                # route approval/interrupt ops without stalling.
                try:
                    while not current_turn_task.done():
                        try:
                            inner_sub = await asyncio.wait_for(
                                self._sq.get(), timeout=0.05
                            )
                        except asyncio.TimeoutError:
                            continue

                        inner_op = inner_sub.op

                        if isinstance(inner_op, ExecApprovalOp):
                            fut = self._pending_approvals.get(inner_op.tool_call_id)
                            if fut and not fut.done():
                                fut.set_result(inner_op.decision)

                        elif isinstance(inner_op, PatchApprovalOp):
                            fut = self._pending_approvals.get(inner_op.tool_call_id)
                            if fut and not fut.done():
                                fut.set_result(inner_op.decision)

                        elif isinstance(inner_op, InterruptOp):
                            cancel_ev.set()

                        # Drain any other ops silently while turn is running
                        # (they will be re-queued or discarded as appropriate)

                    # Collect any exception from the turn task
                    exc = current_turn_task.exception()
                    if exc is not None:
                        from bob.protocol.events import ErrorEvent
                        await self._emit(Event(
                            id=sub_id,
                            msg=ErrorEvent(type="error", message=str(exc))
                        ))

                except asyncio.CancelledError:
                    current_turn_task.cancel()
                    try:
                        await current_turn_task
                    except asyncio.CancelledError:
                        pass
                finally:
                    self._current_turn_cancel = None
                    current_turn_task = None

    # ------------------------------------------------------------------
    # Shell execution helper (user shell commands, outside agent turns)
    # ------------------------------------------------------------------

    async def _run_shell_direct(self, cmd: list[str], cwd: Path, sub_id: str, call_id: str):
        from bob.core.exec import execute_command
        from bob.protocol.events import ExecOutputEvent
        from bob.protocol.config_types import ExecCommandSource

        async def on_delta(data: str, stream: str) -> None:
            await self._emit(Event(id=sub_id, msg=ExecOutputEvent(
                type="exec_output",
                tool_call_id=call_id,
                stream=stream,
                data=data,
            )))

        return await execute_command(
            command=cmd,
            cwd=cwd,
            sandbox=self._sandbox_runner,
            cancel_event=self._current_turn_cancel,
            on_output_delta=on_delta,
        )
