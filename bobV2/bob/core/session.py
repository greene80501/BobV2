from __future__ import annotations
import asyncio
import uuid
import os
import datetime
import json
import logging
from pathlib import Path

logger = logging.getLogger("bob.core.session")
from typing import Optional, AsyncIterator, Any
from bob.config.schema import BobConfig
from bob.paths import bob_home
from bob.protocol.config_types import SandboxPolicy, SandboxMode, AskForApproval
from bob.protocol.ops import (
    Op, Submission, UserTurnOp, InterruptOp, CompactOp, ShutdownOp,
    SetThreadNameOp, RunUserShellCommandOp,
    ListMcpToolsOp, RefreshMcpServersOp, ListSkillsOp,
)
from bob.protocol.events import Event, EventMsg


# ---------------------------------------------------------------------------

class ToolContext:
    """Passed to tool handlers â€” contains session state they need."""

    def __init__(self, session: "BobSession"):
        self.cwd = session.cwd
        self.sandbox = session._sandbox_runner
        self.cancel_event = session._cancel_event
        self.approval_policy = session.config.ask_for_approval
        self.on_output_delta = None  # set per-turn
        self.on_plan_update = None   # set per-turn
        self.on_request_user_input = None
        self.current_tool_call_id = None
        self.attach_image = session.attach_image
        # Back-reference so plan_mode tools can toggle the flag
        self._session = session
        # Task database for task management tools
        self.task_db = session._task_db


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
        # Domains approved for web access this session (key = request_id â†’ Future)
        self._pending_network_approvals: dict[str, asyncio.Future] = {}
        self._pending_dynamic_tool_calls: dict[str, asyncio.Future] = {}
        self._pending_attached_images: list[dict[str, Any]] = []
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

        from bob.core.network_policy import NetworkPolicy
        self._network_policy = NetworkPolicy(
            network_access=config.network_access,
            approved_domains=config.approved_network_domains,
        )

        from bob.sandbox import get_sandbox_runner
        self._sandbox_runner = get_sandbox_runner(sandbox_policy, self.cwd)

        # Context manager for conversation history
        from bob.core.context_manager import ContextManager
        self.context_manager = ContextManager()

        self._api_key = ""
        self._model_compatibility = None
        self._provider_auth = None
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

        # Pending user-input futures keyed by request_id
        self._pending_user_inputs: dict[str, asyncio.Future] = {}

        # Persistence handles â€” populated in _setup_persistence
        self._recorder = None
        self._state_db = None
        self._session_index = None

        # System prompt cache
        self._system_prompt: Optional[str] = None

        # Task database
        from bob.core.task_db import TaskDB
        self._task_db = TaskDB(self.bob_home / "tasks.db")

        # Chrome extension bridge — started in start()
        from bob.bridge.chrome_bridge import ChromeBridge
        self._chrome_bridge = ChromeBridge()

        # MCP and Skills managers — started in start()
        self._mcp_manager = None
        self._skills_manager = None

        # Hook runner — lazily built in the hook_runner property
        self._hook_runner = None

        # Agent control — multi-agent orchestration (parent sessions only)
        if not ephemeral:
            from bob.core.agents.control import AgentControl
            self.agent_control: "AgentControl | None" = AgentControl(self)
        else:
            self.agent_control = None
        self._action_log_path = self._make_action_log_path()
        self._action_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._action_log_handle = self._action_log_path.open("a", encoding="utf-8-sig", buffering=1)
        self._log_action_line(
            f"[session] action log started session={self.session_id} cwd={self.cwd} model={self.config.model}"
        )

    # ------------------------------------------------------------------
    # Hook runner
    # ------------------------------------------------------------------

    @property
    def hook_runner(self) -> "HookRunner":
        """Lazily-built HookRunner for this session's configured hooks."""
        if not hasattr(self, "_hook_runner") or self._hook_runner is None:
            from bob.hooks.runner import HookRunner, HookConfig as RunnerHookConfig
            from bob.protocol.config_types import HookEventName
            runner_hooks: list[RunnerHookConfig] = []
            for h in self.config.hooks:
                raw_event = getattr(h, "event", "")
                try:
                    event = HookEventName(raw_event)
                except ValueError:
                    continue
                raw_cmd = getattr(h, "command", "") or ""
                cmd = raw_cmd.split() if isinstance(raw_cmd, str) and raw_cmd else []
                url = getattr(h, "url", None)
                blocking = getattr(h, "blocking", False)
                runner_hooks.append(RunnerHookConfig(
                    event=event,
                    command=cmd,
                    url=url,
                    mode="sync" if blocking else "async",
                    timeout_seconds=getattr(h, "timeout_seconds", 30),
                ))
            self._hook_runner = HookRunner(runner_hooks)
        return self._hook_runner

    # ------------------------------------------------------------------
    # Bob home helper
    # ------------------------------------------------------------------

    @property
    def bob_home(self) -> Path:
        """Return Bob's user data directory."""
        return bob_home()

    @property
    def action_log_path(self) -> Path:
        return self._action_log_path

    @property
    def current_rollout_path(self) -> Path | None:
        recorder = getattr(self, "_recorder", None)
        return getattr(recorder, "_path", None)

    async def attach_image(
        self,
        path: str,
        mime: str,
        b64: str,
        *,
        detail_level: str = "medium",
    ) -> None:
        normalized_detail = detail_level if detail_level in {"low", "medium", "high"} else "medium"
        self._pending_attached_images.append(
            {
                "path": path,
                "mime": mime,
                "b64": b64,
                "detail": normalized_detail,
            }
        )
        self._log_action_line(
            f"[image] attached path={path} mime={mime} detail={normalized_detail} approx_tokens={len(b64) // 4}"
        )

    def consume_pending_image_message(self) -> dict[str, Any] | None:
        if not self._pending_attached_images:
            return None
        attachments = list(self._pending_attached_images)
        self._pending_attached_images.clear()
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": "Tool attachment(s) for inspection. Use the attached image(s) along with the related tool results.",
            }
        ]
        for item in attachments:
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{item['mime']};base64,{item['b64']}",
                    "detail": item["detail"],
                }
            )
        return {"role": "user", "content": content}

    def _make_action_log_path(self) -> Path:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        return self.bob_home / "logs" / "actions" / f"{stamp}-{self.session_id}.log"

    def _log_action_line(self, text: str) -> None:
        cleaned = str(text).replace("\r", "")
        if not cleaned:
            return
        if not cleaned.endswith("\n"):
            cleaned += "\n"
        self._action_log_handle.write(cleaned)
        self._action_log_handle.flush()

    @staticmethod
    def _format_log_payload(payload: Any, max_chars: int = 4000) -> str:
        try:
            text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            text = str(payload)
        if len(text) > max_chars:
            return text[:max_chars] + "... [truncated]"
        return text

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
        from bob.tools.read_pdf import (
            read_pdf_handler, READ_PDF_DESCRIPTION, READ_PDF_SCHEMA,
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
        from bob.tools.task_create import (
            task_create_handler, TASK_CREATE_DESCRIPTION, TASK_CREATE_SCHEMA,
        )
        from bob.tools.task_update import (
            task_update_handler, TASK_UPDATE_DESCRIPTION, TASK_UPDATE_SCHEMA,
        )
        from bob.tools.task_list import (
            task_list_handler, TASK_LIST_DESCRIPTION, TASK_LIST_SCHEMA,
        )
        from bob.tools.task_get import (
            task_get_handler, TASK_GET_DESCRIPTION, TASK_GET_SCHEMA,
        )
        from bob.tools.task_output import (
            task_output_handler, TASK_OUTPUT_DESCRIPTION, TASK_OUTPUT_SCHEMA,
        )
        from bob.tools.task_stop import (
            task_stop_handler, TASK_STOP_DESCRIPTION, TASK_STOP_SCHEMA,
        )
        from bob.tools.request_user_input import (
            request_user_input_handler, REQUEST_USER_INPUT_DESCRIPTION, REQUEST_USER_INPUT_SCHEMA,
        )
        from bob.tools.tool_search import (
            tool_search_handler, TOOL_SEARCH_DESCRIPTION, TOOL_SEARCH_SCHEMA,
        )
        from bob.tools.git_worktree import (
            enter_worktree_handler, ENTER_WORKTREE_DESCRIPTION, ENTER_WORKTREE_SCHEMA,
            exit_worktree_handler, EXIT_WORKTREE_DESCRIPTION, EXIT_WORKTREE_SCHEMA,
        )
        from bob.tools.lsp_tools import (
            lsp_diagnostics_handler, LSP_DIAGNOSTICS_DESCRIPTION, LSP_DIAGNOSTICS_SCHEMA,
            lsp_hover_handler, LSP_HOVER_DESCRIPTION, LSP_HOVER_SCHEMA,
            lsp_definition_handler, LSP_DEFINITION_DESCRIPTION, LSP_DEFINITION_SCHEMA,
            lsp_references_handler, LSP_REFERENCES_DESCRIPTION, LSP_REFERENCES_SCHEMA,
            lsp_rename_handler, LSP_RENAME_DESCRIPTION, LSP_RENAME_SCHEMA,
        )
        from bob.tools.ide_bridge import (
            ide_get_open_files_handler, IDE_GET_OPEN_FILES_DESCRIPTION, IDE_GET_OPEN_FILES_SCHEMA,
            ide_get_selection_handler, IDE_GET_SELECTION_DESCRIPTION, IDE_GET_SELECTION_SCHEMA,
            ide_get_diagnostics_handler, IDE_GET_DIAGNOSTICS_DESCRIPTION, IDE_GET_DIAGNOSTICS_SCHEMA,
            ide_get_active_file_handler, IDE_GET_ACTIVE_FILE_DESCRIPTION, IDE_GET_ACTIVE_FILE_SCHEMA,
        )

        # Core tools
        self.tool_registry.register(
            "shell", SHELL_TOOL_DESCRIPTION, SHELL_TOOL_SCHEMA, shell_handler,
            is_mutating=True,
            supports_parallel=False,
            emits_exec_events=True,
        )
        self.tool_registry.register(
            "update_plan", UPDATE_PLAN_DESCRIPTION, UPDATE_PLAN_SCHEMA, update_plan_handler,
            is_mutating=False,
            supports_parallel=False,
        )
        self.tool_registry.register(
            "view_image", VIEW_IMAGE_DESCRIPTION, VIEW_IMAGE_SCHEMA, view_image_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "list_dir", LIST_DIR_DESCRIPTION, LIST_DIR_SCHEMA, list_dir_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        # Phase 1 â€” file tools
        self.tool_registry.register(
            "read_file", READ_FILE_DESCRIPTION, READ_FILE_SCHEMA, read_file_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "read_pdf", READ_PDF_DESCRIPTION, READ_PDF_SCHEMA, read_pdf_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "write_file", WRITE_FILE_DESCRIPTION, WRITE_FILE_SCHEMA, write_file_handler
        )
        self.tool_registry.register(
            "edit_file", EDIT_FILE_DESCRIPTION, EDIT_FILE_SCHEMA, edit_file_handler
        )
        self.tool_registry.register(
            "glob_files", GLOB_FILES_DESCRIPTION, GLOB_FILES_SCHEMA, glob_files_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "grep_files", GREP_FILES_DESCRIPTION, GREP_FILES_SCHEMA, grep_files_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        # Phase 2 â€” utilities
        self.tool_registry.register(
            "sleep", SLEEP_DESCRIPTION, SLEEP_SCHEMA, sleep_handler,
            is_mutating=False,
            supports_parallel=False,
        )
        self.tool_registry.register(
            "todo_write", TODO_WRITE_DESCRIPTION, TODO_WRITE_SCHEMA, todo_write_handler
        )
        self.tool_registry.register(
            "enter_plan_mode", ENTER_PLAN_MODE_DESCRIPTION, ENTER_PLAN_MODE_SCHEMA,
            enter_plan_mode_handler,
            is_mutating=True,
            supports_parallel=False,
        )
        self.tool_registry.register(
            "exit_plan_mode", EXIT_PLAN_MODE_DESCRIPTION, EXIT_PLAN_MODE_SCHEMA,
            exit_plan_mode_handler,
            is_mutating=True,
            supports_parallel=False,
        )
        from bob.protocol.config_types import WebSearchMode
        if self.config.web_search_mode != WebSearchMode.DISABLED:
            self.tool_registry.register(
                "web_search", WEB_SEARCH_DESCRIPTION, WEB_SEARCH_SCHEMA, web_search_handler,
                is_mutating=False,
                supports_parallel=True,
                requires_network_approval=True,
            )
        self.tool_registry.register(
            "web_fetch", WEB_FETCH_DESCRIPTION, WEB_FETCH_SCHEMA, web_fetch_handler,
            is_mutating=False,
            supports_parallel=True,
            requires_network_approval=True,
        )
        # Cron / schedule tools
        from bob.tools.cron_tools import (
            schedule_cron_handler, SCHEDULE_CRON_DESCRIPTION, SCHEDULE_CRON_SCHEMA,
            remote_trigger_handler, REMOTE_TRIGGER_DESCRIPTION, REMOTE_TRIGGER_SCHEMA,
        )
        self.tool_registry.register(
            "schedule_cron", SCHEDULE_CRON_DESCRIPTION, SCHEDULE_CRON_SCHEMA, schedule_cron_handler
        )
        self.tool_registry.register(
            "remote_trigger", REMOTE_TRIGGER_DESCRIPTION, REMOTE_TRIGGER_SCHEMA, remote_trigger_handler
        )
        # Phase 5 â€” advanced
        self.tool_registry.register(
            "js_repl", JS_REPL_DESCRIPTION, JS_REPL_SCHEMA, js_repl_handler,
            is_mutating=True,
            supports_parallel=False,
        )
        self.tool_registry.register(
            "notebook_read", NOTEBOOK_READ_DESCRIPTION, NOTEBOOK_READ_SCHEMA, notebook_read_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "notebook_edit", NOTEBOOK_EDIT_DESCRIPTION, NOTEBOOK_EDIT_SCHEMA, notebook_edit_handler
        )
        # Phase 4 â€” multi-agent
        # Task management tools
        self.tool_registry.register(
            "task_create", TASK_CREATE_DESCRIPTION, TASK_CREATE_SCHEMA, task_create_handler
        )
        self.tool_registry.register(
            "task_update", TASK_UPDATE_DESCRIPTION, TASK_UPDATE_SCHEMA, task_update_handler
        )
        self.tool_registry.register(
            "task_list", TASK_LIST_DESCRIPTION, TASK_LIST_SCHEMA, task_list_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "task_get", TASK_GET_DESCRIPTION, TASK_GET_SCHEMA, task_get_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "task_output", TASK_OUTPUT_DESCRIPTION, TASK_OUTPUT_SCHEMA, task_output_handler
        )
        self.tool_registry.register(
            "task_stop", TASK_STOP_DESCRIPTION, TASK_STOP_SCHEMA, task_stop_handler
        )
        # User interaction tool
        self.tool_registry.register(
            "request_user_input", REQUEST_USER_INPUT_DESCRIPTION, REQUEST_USER_INPUT_SCHEMA,
            request_user_input_handler,
            is_mutating=False,
            supports_parallel=False,
        )
        self.tool_registry.register(
            "tool_search", TOOL_SEARCH_DESCRIPTION, TOOL_SEARCH_SCHEMA, tool_search_handler,
            is_mutating=False,
            supports_parallel=True,
            source="core",
        )
        # Git worktree tools
        self.tool_registry.register(
            "enter_worktree", ENTER_WORKTREE_DESCRIPTION, ENTER_WORKTREE_SCHEMA,
            enter_worktree_handler
        )
        self.tool_registry.register(
            "exit_worktree", EXIT_WORKTREE_DESCRIPTION, EXIT_WORKTREE_SCHEMA,
            exit_worktree_handler
        )
        # LSP integration tools
        self.tool_registry.register(
            "lsp_diagnostics", LSP_DIAGNOSTICS_DESCRIPTION, LSP_DIAGNOSTICS_SCHEMA,
            lsp_diagnostics_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "lsp_hover", LSP_HOVER_DESCRIPTION, LSP_HOVER_SCHEMA,
            lsp_hover_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "lsp_definition", LSP_DEFINITION_DESCRIPTION, LSP_DEFINITION_SCHEMA,
            lsp_definition_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "lsp_references", LSP_REFERENCES_DESCRIPTION, LSP_REFERENCES_SCHEMA,
            lsp_references_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "lsp_rename", LSP_RENAME_DESCRIPTION, LSP_RENAME_SCHEMA,
            lsp_rename_handler
        )
        # IDE bridge tools
        self.tool_registry.register(
            "ide_get_open_files", IDE_GET_OPEN_FILES_DESCRIPTION, IDE_GET_OPEN_FILES_SCHEMA,
            ide_get_open_files_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "ide_get_selection", IDE_GET_SELECTION_DESCRIPTION, IDE_GET_SELECTION_SCHEMA,
            ide_get_selection_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "ide_get_diagnostics", IDE_GET_DIAGNOSTICS_DESCRIPTION, IDE_GET_DIAGNOSTICS_SCHEMA,
            ide_get_diagnostics_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        self.tool_registry.register(
            "ide_get_active_file", IDE_GET_ACTIVE_FILE_DESCRIPTION, IDE_GET_ACTIVE_FILE_SCHEMA,
            ide_get_active_file_handler,
            is_mutating=False,
            supports_parallel=True,
        )
        # Computer use tool — only register when the user has explicitly enabled it
        _computer_use_enabled = bool(
            self.config.feature_flags.get("computer_use", False)
            or getattr(self.config, "enable_computer_use", False)
        )
        if _computer_use_enabled:
            from bob.tools.computer_use import (
                computer_use_handler, COMPUTER_USE_SCHEMA,
            )
            _cu_desc = (
                "Control the user's GUI. The user has explicitly enabled this tool "
                "via feature_flags.computer_use=true in their config. "
                "Available actions: screenshot (returns base64 PNG), left_click, "
                "right_click, double_click, mouse_move, scroll, key (e.g. 'ctrl+c'), "
                "type (types text), cursor_position. "
                "Use 'screenshot' first to see the current screen state before clicking."
            )
            self.tool_registry.register(
                "computer_use", _cu_desc, COMPUTER_USE_SCHEMA,
                computer_use_handler,
                is_mutating=True,
                supports_parallel=False,
                source="core",
                keywords=["gui", "screenshot", "click", "mouse", "keyboard", "type"],
            )
        # Chrome browser control tool
        from bob.tools.browser import browser_handler, BROWSER_DESCRIPTION, BROWSER_SCHEMA
        self.tool_registry.register(
            "browser", BROWSER_DESCRIPTION, BROWSER_SCHEMA, browser_handler,
            is_mutating=True,
            supports_parallel=False,
            source="core",
            keywords=["chrome", "browser", "navigate", "screenshot", "click", "web", "tab"],
        )
        # MCP OAuth auth tool
        from bob.tools.mcp_auth_tool import (
            mcp_authenticate_handler, MCP_AUTHENTICATE_DESCRIPTION, MCP_AUTHENTICATE_SCHEMA,
        )
        self.tool_registry.register(
            "mcp_authenticate", MCP_AUTHENTICATE_DESCRIPTION, MCP_AUTHENTICATE_SCHEMA,
            mcp_authenticate_handler,
            source="mcp",
        )
        # Multi-agent tools (only for non-ephemeral sessions)
        if not self.ephemeral:
            from bob.tools.agents import (
                spawn_agents_handler, SPAWN_AGENTS_DESCRIPTION, SPAWN_AGENTS_SCHEMA,
                spawn_agent_handler, SPAWN_AGENT_DESCRIPTION, SPAWN_AGENT_SCHEMA,
                wait_agent_handler, WAIT_AGENT_DESCRIPTION, WAIT_AGENT_SCHEMA,
                send_message_handler, SEND_MESSAGE_DESCRIPTION, SEND_MESSAGE_SCHEMA,
                assign_task_handler, ASSIGN_TASK_DESCRIPTION, ASSIGN_TASK_SCHEMA,
                close_agent_handler, CLOSE_AGENT_DESCRIPTION, CLOSE_AGENT_SCHEMA,
                list_agents_handler, LIST_AGENTS_DESCRIPTION, LIST_AGENTS_SCHEMA,
            )
            self.tool_registry.register(
                "spawn_agents", SPAWN_AGENTS_DESCRIPTION, SPAWN_AGENTS_SCHEMA,
                spawn_agents_handler,
                is_mutating=True,
                supports_parallel=False,
                source="agents",
                keywords=["agents", "parallel", "spawn", "workers", "batch", "team"],
            )
            self.tool_registry.register(
                "spawn_agent", SPAWN_AGENT_DESCRIPTION, SPAWN_AGENT_SCHEMA,
                spawn_agent_handler,
                is_mutating=True,
                supports_parallel=False,
                expose_to_model=False,
                source="agents",
                keywords=["agent", "spawn", "legacy", "worker", "background"],
            )
            self.tool_registry.register(
                "wait_agent", WAIT_AGENT_DESCRIPTION, WAIT_AGENT_SCHEMA,
                wait_agent_handler,
                is_mutating=False,
                supports_parallel=False,
                source="agents",
                keywords=["agent", "wait", "join", "result"],
            )
            self.tool_registry.register(
                "send_message", SEND_MESSAGE_DESCRIPTION, SEND_MESSAGE_SCHEMA,
                send_message_handler,
                is_mutating=True,
                supports_parallel=False,
                source="agents",
                keywords=["agent", "message", "communicate"],
            )
            self.tool_registry.register(
                "assign_task", ASSIGN_TASK_DESCRIPTION, ASSIGN_TASK_SCHEMA,
                assign_task_handler,
                is_mutating=True,
                supports_parallel=False,
                source="agents",
                keywords=["agent", "task", "assign", "redirect"],
            )
            self.tool_registry.register(
                "close_agent", CLOSE_AGENT_DESCRIPTION, CLOSE_AGENT_SCHEMA,
                close_agent_handler,
                is_mutating=True,
                supports_parallel=False,
                source="agents",
                keywords=["agent", "close", "cancel", "stop", "kill"],
            )
            self.tool_registry.register(
                "list_agents", LIST_AGENTS_DESCRIPTION, LIST_AGENTS_SCHEMA,
                list_agents_handler,
                is_mutating=False,
                supports_parallel=True,
                source="agents",
                keywords=["agent", "list", "status", "running"],
            )

        # MCP resource tools
        from bob.tools.mcp_resource_tools import (
            mcp_list_resources_handler, MCP_LIST_RESOURCES_DESCRIPTION, MCP_LIST_RESOURCES_SCHEMA,
            mcp_read_resource_handler, MCP_READ_RESOURCE_DESCRIPTION, MCP_READ_RESOURCE_SCHEMA,
        )
        self.tool_registry.register(
            "mcp_list_resources", MCP_LIST_RESOURCES_DESCRIPTION, MCP_LIST_RESOURCES_SCHEMA,
            mcp_list_resources_handler,
            is_mutating=False,
            supports_parallel=True,
            source="mcp",
        )
        self.tool_registry.register(
            "mcp_read_resource", MCP_READ_RESOURCE_DESCRIPTION, MCP_READ_RESOURCE_SCHEMA,
            mcp_read_resource_handler,
            is_mutating=False,
            supports_parallel=True,
            source="mcp",
        )

    async def request_user_input(self, request_id: str, prompt: str, fields: list) -> str:
        """Called by ask_user tool â€” creates a future and waits for UserInputAnswerOp."""
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
    # Client factory â€” routes by model to Responses API or LiteLLM
    # ------------------------------------------------------------------

    # Models that only work with OpenAI's Responses API (not Chat Completions).
    # LiteLLM routes to /v1/chat/completions; these must go through BobClient.
    def get_model_runtime(self, model: Optional[str] = None):
        from bob.llm.compatibility import get_model_compatibility, resolve_provider_auth

        selected_model = model or self.config.model
        compatibility = get_model_compatibility(selected_model)
        provider_auth = resolve_provider_auth(
            selected_model,
            self.config,
            compatibility=compatibility,
        )
        return compatibility, provider_auth

    def describe_model_runtime(self, model: Optional[str] = None) -> dict[str, Any]:
        compatibility, provider_auth = self.get_model_runtime(model)
        return {
            "requested_model": compatibility.requested_model,
            "canonical_model": compatibility.canonical_model,
            "bare_model": compatibility.bare_model,
            "provider": compatibility.provider,
            "route": compatibility.route.value,
            "support_level": compatibility.support_level.value,
            "supports_reasoning_effort": compatibility.supports_reasoning_effort,
            "supports_thinking_budget": compatibility.supports_thinking_budget,
            "supports_prompt_caching": compatibility.supports_prompt_caching,
            "supports_vision": compatibility.supports_vision,
            "supports_service_tier": compatibility.supports_service_tier,
            "missing_auth": list(provider_auth.missing),
            "used_global_fallback": provider_auth.used_global_fallback,
            "notes": list(compatibility.notes),
        }

    def _unused_make_client_legacy(self, model: str):
        """Return the right client for the selected model and provider."""
        bare = model.split("/")[-1]  # strip provider prefix e.g. "openai/gpt-4o" â†’ "gpt-4o"
        if True:
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
        # Fire-and-forget keepalive to warm the TCP/TLS connection before the
        # user submits their first message.
        asyncio.create_task(self._prewarm_connection())
        # Start MCP servers and skills discovery in the background so they
        # don't delay the session_started event.
        asyncio.create_task(self._start_mcp())
        asyncio.create_task(self._start_skills())
        asyncio.create_task(self._start_chrome_bridge())

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

    async def _unused_prewarm_connection_legacy(self) -> None:
        """Send a minimal request to warm the TCP+TLS connection before the user types."""
        try:
            base_url = self.config.base_url.rstrip("/")
            import urllib.request
            req = urllib.request.Request(
                f"{base_url}/models",
                headers={
                    "Authorization": f"Bearer {self._api_key or ''}",
                    "Content-Type": "application/json",
                },
            )
            # Use a very short timeout â€” we don't care about the result
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass  # Best-effort; never block the session

    def _make_client(self, model: str):
        """Return the right client for the selected model and provider."""
        from bob.llm.compatibility import ClientRoute

        compatibility, provider_auth = self.get_model_runtime(model)
        self._model_compatibility = compatibility
        self._provider_auth = provider_auth
        self._api_key = provider_auth.api_key

        if compatibility.route == ClientRoute.OPENAI_RESPONSES:
            from bob.client.openai_client import BobClient

            kwargs: dict[str, Any] = {
                "api_key": provider_auth.api_key,
                "model": compatibility.canonical_model,
            }
            if provider_auth.base_url:
                kwargs["base_url"] = provider_auth.base_url
            return BobClient(**kwargs)

        from bob.llm.client import LiteLLMClient

        env_overrides = dict(provider_auth.env_overrides)
        proxy_url = self.config.network_proxy or ""
        if proxy_url:
            env_overrides.setdefault("HTTP_PROXY", proxy_url)
            env_overrides.setdefault("HTTPS_PROXY", proxy_url)

        return LiteLLMClient(
            api_key=provider_auth.api_key,
            model=compatibility.canonical_model,
            base_url=provider_auth.base_url,
            provider_kwargs=provider_auth.provider_kwargs,
            env_overrides=env_overrides,
            default_timeout_seconds=float(
                getattr(self.config, "provider_stream_idle_timeout_seconds", 90) or 90
            ),
        )

    async def _prewarm_connection(self) -> None:
        """Warm the connection for the active provider when it is safe to do so."""
        try:
            compatibility, provider_auth = self.get_model_runtime(self.config.model)
            if compatibility.route.value != "openai_responses":
                return
            if not provider_auth.base_url or not provider_auth.api_key:
                return

            base_url = provider_auth.base_url.rstrip("/")
            import urllib.request

            req = urllib.request.Request(
                f"{base_url}/models",
                headers={
                    "Authorization": f"Bearer {provider_auth.api_key}",
                    "Content-Type": "application/json",
                },
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # MCP lifecycle
    # ------------------------------------------------------------------

    def _plugin_roots(self) -> list[Path]:
        """Return Bob-owned local plugin roots in discovery order."""
        roots = [self.bob_home / "plugins", self.cwd / ".bob" / "plugins"]
        unique_roots: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root.resolve())
            if key in seen:
                continue
            seen.add(key)
            unique_roots.append(root)
        return unique_roots

    @staticmethod
    def _plugin_skill_metadata(skill_infos: list) -> list:
        """Convert plugin skill descriptors into SkillMetadata records."""
        from bob.protocol.items import SkillMetadata

        metadata: list[SkillMetadata] = []
        for info in skill_infos:
            metadata.append(SkillMetadata(
                name=info.name,
                description=info.description,
                short_description=info.short_description or None,
                path=info.plugin_path,
                scope="plugin",
                enabled=True,
                user_invocable=info.user_invocable,
                allowed_tools=list(info.allowed_tools),
                content_file=info.content_file,
            ))
        return metadata

    async def _start_mcp(self) -> None:
        """Connect to all configured MCP servers and register their tools."""
        import re
        from bob.mcp.manager import McpManager
        from bob.protocol.events import McpStartupStatusEvent
        from bob.plugins.manager import PluginsManager

        servers = dict(self.config.mcp_servers)

        local_mcp_cfgs, _ = PluginsManager.load_plugin_bundles_from_roots(self._plugin_roots())
        for cfg in local_mcp_cfgs:
            if cfg.server_name not in servers:
                if cfg.transport == "stdio":
                    servers[cfg.server_name] = {
                        "type": "stdio",
                        "command": cfg.command,
                        "args": cfg.args,
                        "env": cfg.env,
                    }
                else:
                    servers[cfg.server_name] = {
                        "type": cfg.transport,
                        "url": cfg.url,
                        "headers": cfg.headers,
                        "env": cfg.env,
                    }

        # Import from Claude Code plugins if requested
        if self.config.import_claude_mcp or getattr(self.config, "claude_plugins_path", None):
            pm = PluginsManager(self.bob_home / "plugins")
            mcp_cfgs, _ = pm.load_claude_code_plugins(
                claude_plugins_dir=self.config.claude_plugins_path
            )
            for cfg in mcp_cfgs:
                if cfg.server_name not in servers:
                    if cfg.transport == "stdio":
                        servers[cfg.server_name] = {
                            "type": "stdio",
                            "command": cfg.command,
                            "args": cfg.args,
                            "env": cfg.env,
                        }
                    else:
                        servers[cfg.server_name] = {
                            "type": cfg.transport,
                            "url": cfg.url,
                            "headers": cfg.headers,
                            "env": cfg.env,
                        }

        if not servers:
            return

        self._mcp_manager = McpManager(servers)
        results = await self._mcp_manager.start()
        self._register_mcp_tools()

        connected = [n for n, ok in results.items() if ok]
        failed = [n for n, ok in results.items() if not ok]
        total_tools = len(self._mcp_manager.get_all_tools())

        await self._emit(Event(
            id="mcp",
            msg=McpStartupStatusEvent(
                type="mcp_startup_status",
                connected=connected,
                failed=failed,
                total_tools=total_tools,
            )
        ))

    def _register_mcp_tools(self) -> None:
        """Register all MCP tools into the ToolRegistry."""
        import re

        if not self._mcp_manager:
            return

        for tool in self._mcp_manager.get_all_tools():
            raw_name = f"{tool.server_name}__{tool.name}"
            safe_name = re.sub(r"[^A-Za-z0-9_.:\-]", "_", raw_name)
            if not safe_name or not safe_name[0].isalpha():
                safe_name = f"mcp_{safe_name}"
            description = f"[{tool.server_name}] {tool.description}"
            captured_name = raw_name
            mcp_mgr = self._mcp_manager

            async def _handler(tc, args, _name=captured_name, _mgr=mcp_mgr):
                return await _mgr.call_tool(_name, args)

            self.tool_registry.register(
                safe_name,
                description,
                tool.input_schema,
                _handler,
                is_mutating=True,
                source="mcp",
            )

    # ------------------------------------------------------------------
    # Skills lifecycle
    # ------------------------------------------------------------------

    async def _start_chrome_bridge(self) -> None:
        """Start the Chrome extension WebSocket bridge."""
        try:
            await self._chrome_bridge.start()
        except Exception as exc:
            logger.debug("Chrome bridge failed to start: %s", exc)

    async def _start_skills(self) -> None:
        """Initialize the skills manager."""
        if not self.config.enable_skills:
            return
        from bob.skills.manager import SkillsManager
        from bob.plugins.manager import PluginsManager
        self._skills_manager = SkillsManager(self.bob_home)
        plugin_skills = []
        _, local_skill_infos = PluginsManager.load_plugin_bundles_from_roots(self._plugin_roots())
        plugin_skills.extend(self._plugin_skill_metadata(local_skill_infos))

        if self.config.import_claude_mcp or getattr(self.config, "claude_plugins_path", None):
            pm = PluginsManager(self.bob_home / "plugins")
            _, claude_skill_infos = pm.load_claude_code_plugins(
                claude_plugins_dir=self.config.claude_plugins_path
            )
            plugin_skills.extend(self._plugin_skill_metadata(claude_skill_infos))

        self._skills_manager.set_extra_skills(plugin_skills)
        # Eagerly discover skills so they're ready for the first turn
        try:
            self._skills_manager.discover(cwd=self.cwd)
        except Exception:
            pass

    def list_skills(self, cwd: Optional[Path] = None) -> list:
        """Return all discovered skills."""
        if not self._skills_manager:
            return []
        return self._skills_manager.list_all(cwd=cwd or self.cwd)

    async def invoke_skill(self, skill_name: str, arguments: str = "") -> None:
        """Invoke a skill by injecting it as a developer_message_override turn."""
        if not self._skills_manager:
            return
        skill = self._skills_manager.find(skill_name, cwd=self.cwd)
        if skill is None:
            return
        skill_dir = skill.path
        content_path = skill_dir / skill.content_file
        if not content_path.exists():
            return
        template = content_path.read_text(encoding="utf-8")
        # Strip YAML frontmatter from SKILL.md files
        if template.startswith("---"):
            end = template.find("\n---", 3)
            if end != -1:
                template = template[end + 4:].lstrip("\n")
        prompt = template.replace("$ARGUMENTS", arguments)
        await self.submit(UserTurnOp(
            type="user_turn",
            items=[],
            developer_message_override=prompt,
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

        db_path = bob_home / "state.sqlite"
        self._state_db = StateDb(db_path)
        await self._state_db.connect()
        self._session_index = SessionIndex(self._state_db)

        ts = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        rollout_path = sessions_dir / f"{ts}-{self.session_id[:8]}.jsonl"
        await self._switch_persistence_target(
            session_id=self.session_id,
            rollout_path=rollout_path,
            append_existing=False,
        )

    async def _switch_persistence_target(
        self,
        *,
        session_id: str,
        rollout_path: Path,
        append_existing: bool,
    ) -> None:
        """Rotate recorder + index entry to a specific session/thread."""
        if self.ephemeral or self._state_db is None:
            self.session_id = session_id
            return

        from bob.rollout.recorder import RolloutRecorder

        if self._recorder is not None:
            await self._recorder.stop()

        self.session_id = session_id
        self._recorder = RolloutRecorder(
            path=rollout_path,
            session_id=self.session_id,
            model=self.config.model,
            cwd=str(self.cwd),
        )
        if append_existing:
            await self._recorder.start_append()
        else:
            await self._recorder.start()

        await self._state_db.upsert_thread(
            id=self.session_id,
            name=None,
            path=str(rollout_path),
            model=self.config.model,
            cwd=str(self.cwd),
        )

    def _build_new_rollout_path(self, session_id: str) -> Path:
        ts = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        sessions_dir = self.bob_home / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        return sessions_dir / f"{ts}-{session_id[:8]}.jsonl"

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

        # Add output style directive
        from bob.protocol.config_types import OutputStyle
        if self.config.output_style == OutputStyle.BRIEF:
            base += (
                "\n\n# OUTPUT STYLE: BRIEF\n"
                "- Be extremely concise\n"
                "- One sentence answers when possible\n"
                "- No explanations unless asked\n"
                "- Skip pleasantries and acknowledgments\n"
                "- Get straight to the point"
            )
        elif self.config.output_style == OutputStyle.VERBOSE:
            base += (
                "\n\n# OUTPUT STYLE: VERBOSE\n"
                "- Provide detailed explanations\n"
                "- Include reasoning and context\n"
                "- Explain trade-offs and alternatives\n"
                "- Add examples when helpful\n"
                "- Be thorough and educational"
            )
        # NORMAL style has no extra directive

        # Add collaboration mode directive
        from bob.protocol.config_types import CollaborationModeKind
        collab_mode = self.config.collaboration_mode.mode
        if collab_mode == CollaborationModeKind.PLAN:
            base += (
                "\n\n# COLLABORATION MODE: PLAN\n"
                "- You are in planning mode. Use read-only tools and stay in the main thread unless there are at least two substantial independent research tracks.\n"
                "- If you delegate, decompose first and spawn multiple workers in parallel; never spawn a single worker.\n"
                "- Do NOT write or edit files until the user approves the plan.\n"
                "- Produce a detailed, step-by-step plan with clear deliverables."
            )
        elif collab_mode == CollaborationModeKind.PAIR_PROGRAMMING:
            base += (
                "\n\n# COLLABORATION MODE: PAIR PROGRAMMING\n"
                "- Work closely with the user. Explain your reasoning as you go.\n"
                "- Suggest alternatives and ask clarifying questions when appropriate.\n"
                "- Use sub-agents only for real parallel work. If the task does not need multiple workers, stay in the main thread.\n"
                "- Decompose first. Spawn multiple workers only when there are at least two substantial independent tracks.\n"
                "- Use the worker task prompt to define whether each worker should plan, inspect, implement, or review."
            )
        elif collab_mode == CollaborationModeKind.EXECUTE:
            base += (
                "\n\n# COLLABORATION MODE: EXECUTE\n"
                "- Focus on getting things done with minimal back-and-forth.\n"
                "- Use sub-agents only for true parallelism. Never spawn a single worker.\n"
                "- Decompose first. Spawn multiple workers only when there are at least two substantial independent tracks.\n"
                "- Use the worker task prompt to specify whether each worker should research, plan, implement, or test/review.\n"
                "- For coding work, parallel workers should have clearly separated scope ownership.\n"
                "- Wait for all workers to finish before synthesizing the final response.\n"
                "- Only ask the user for input when truly blocked."
            )
        # DEFAULT mode has no extra directive

        self._system_prompt = base

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit(self, op: Op) -> str:
        sub = Submission(op=op)
        await self._sq.put(sub)
        op_type = getattr(op, "type", op.__class__.__name__)
        payload = op.model_dump() if hasattr(op, "model_dump") else str(op)
        self._log_action_line(
            f"[submit] id={sub.id} type={op_type} payload={self._format_log_payload(payload)}"
        )
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

        msg_type = event.msg.type if hasattr(event.msg, "type") else event.msg.__class__.__name__
        payload = event.msg.model_dump() if hasattr(event.msg, "model_dump") else str(event.msg)
        self._log_action_line(
            f"[event] id={event.id} type={msg_type} payload={self._format_log_payload(payload)}"
        )

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
        new_id = str(uuid.uuid4())
        if not self.ephemeral and self._state_db is not None:
            await self._switch_persistence_target(
                session_id=new_id,
                rollout_path=self._build_new_rollout_path(new_id),
                append_existing=False,
            )
        else:
            self.session_id = new_id
        await self._load_system_prompt()

    async def resume(self, path: str, session_id: Optional[str] = None) -> None:
        """Load history from a rollout file."""
        from bob.rollout.recorder import load_rollout
        from bob.core.rollout_reconstruction import reconstruct_history

        items = await load_rollout(Path(path))
        result = reconstruct_history(items)
        self.context_manager.replace(result.history)
        if result.previous_model:
            self.config = self.config.model_copy(update={"model": result.previous_model})
            self.client = self._make_client(self.config.model)
        if not self.ephemeral and self._state_db is not None:
            target_session_id = session_id or self.session_id
            await self._switch_persistence_target(
                session_id=target_session_id,
                rollout_path=Path(path),
                append_existing=True,
            )

    async def resume_by_id(self, session_id: str) -> None:
        if self._session_index:
            record = await self._session_index.find_by_id(session_id)
            if record and record.path:
                await self.resume(record.path, session_id=record.id)

    async def fork(self, path: str) -> None:
        """Fork from an existing session's history, creating a new session_id."""
        await self.resume(path)
        new_id = str(uuid.uuid4())
        if not self.ephemeral and self._state_db is not None:
            await self._switch_persistence_target(
                session_id=new_id,
                rollout_path=self._build_new_rollout_path(new_id),
                append_existing=False,
            )
        else:
            self.session_id = new_id

    async def list_sessions(self):
        if self._session_index:
            return await self._session_index.list_sessions(sort_by="updated_at")
        return []

    async def _touch_session_activity(self, preview: Optional[str], *, turn_completed: bool = True) -> None:
        if self.ephemeral or self._state_db is None:
            return
        try:
            await self._state_db.touch_thread_activity(
                self.session_id,
                preview=preview[:300] if preview else None,
                increment_turn_count=turn_completed,
            )
        except Exception:
            pass

    def _preview_from_user_turn(self, op: UserTurnOp) -> str:
        parts: list[str] = []
        for item in getattr(op, "items", []) or []:
            text = getattr(item, "text", None)
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
                continue
            if isinstance(item, dict):
                v = item.get("text")
                if isinstance(v, str) and v.strip():
                    parts.append(v.strip())
        merged = " ".join(parts).strip()
        if len(merged) > 280:
            return merged[:280] + "..."
        return merged

    async def submit_compact(self) -> None:
        await self.submit(CompactOp(type="compact"))

    async def _record_compaction_checkpoint(self, result) -> None:
        if not self._recorder:
            return
        await self._recorder.write({
            "type": "compacted",
            "reason": result.reason,
            "summary": result.summary_text,
            "token_before": result.token_before,
            "token_after": result.token_after,
            "replacement_history": result.new_history,
        })

    async def compact_history(
        self,
        *,
        reason: str,
        sub_id: str = "system",
        hint: str | None = None,
    ):
        from bob.core.compact import run_compact
        from bob.protocol.events import (
            ContextCompactionEvent,
            HistoryCompactedEvent,
            WarningEvent,
        )

        result = await run_compact(self, reason=reason, hint=hint)
        if not result:
            if hasattr(self, "analytics") and self.analytics is not None:
                self.analytics.record_compaction(
                    reason=reason,
                    token_before=self.context_manager.approx_token_count(),
                    token_after=self.context_manager.approx_token_count(),
                    success=False,
                )
            await self._emit(Event(
                id=sub_id,
                msg=ContextCompactionEvent(
                    type="context_compaction",
                    reason=reason,
                    token_before=self.context_manager.approx_token_count(),
                    token_after=self.context_manager.approx_token_count(),
                    success=False,
                ),
            ))
            return None

        # Guardrail: reject non-effective compactions to avoid compaction loops.
        # Require at least 5% reduction unless the history is already very small.
        if result.token_before > 20_000 and result.token_after >= int(result.token_before * 0.95):
            if hasattr(self, "analytics") and self.analytics is not None:
                self.analytics.record_compaction(
                    reason=reason,
                    token_before=result.token_before,
                    token_after=result.token_after,
                    success=False,
                )
            await self._emit(Event(
                id=sub_id,
                msg=ContextCompactionEvent(
                    type="context_compaction",
                    reason=reason,
                    token_before=result.token_before,
                    token_after=result.token_after,
                    success=False,
                ),
            ))
            return None

        self.context_manager.replace(result.new_history)
        await self._record_compaction_checkpoint(result)
        if hasattr(self, "analytics") and self.analytics is not None:
            self.analytics.record_compaction(
                reason=reason,
                token_before=result.token_before,
                token_after=result.token_after,
                success=True,
            )
        await self._emit(Event(
            id=sub_id,
            msg=ContextCompactionEvent(
                type="context_compaction",
                reason=reason,
                token_before=result.token_before,
                token_after=result.token_after,
                success=True,
            ),
        ))
        await self._emit(Event(
            id=sub_id,
            msg=HistoryCompactedEvent(
                type="history_compacted",
                summary=result.summary_text[:500],
                turns_removed=0,
            ),
        ))
        await self._emit(Event(
            id=sub_id,
            msg=WarningEvent(
                type="warning",
                message=(
                    "Heads up: Long threads and multiple compactions can cause "
                    "the model to be less accurate. Start a new thread when possible."
                ),
            ),
        ))
        return result

    def _lightweight_trim_context(self) -> int:
        removed = 0
        removed += self.context_manager.trim_oldest_tool_results(keep_recent=40)
        removed += self.context_manager.trim_oldest_assistant_messages(keep_recent=24)
        return removed

    async def manage_context_pre_turn(self, sub_id: str) -> None:
        from bob.core.context_budget import compute_context_budget, should_compact

        token_count = self.context_manager.approx_token_count()
        budget = compute_context_budget(self)
        threshold = self.config.auto_compact_threshold_tokens
        if not should_compact(token_count, budget, threshold):
            return

        removed = self._lightweight_trim_context()
        if removed > 0:
            token_count = self.context_manager.approx_token_count()
            if not should_compact(token_count, budget, threshold):
                return

        await self.compact_history(reason="pre_turn_threshold", sub_id=sub_id)

    async def submit_set_name(self, name: str) -> None:
        await self.submit(SetThreadNameOp(type="set_thread_name", name=name))

    async def shutdown(self) -> None:
        self._shutdown_event.set()
        self._log_action_line("[session] shutdown requested")
        if getattr(self, "agent_control", None) is not None:
            try:
                await self.agent_control.shutdown()
            except Exception:
                pass
        if self._agent_task:
            self._agent_task.cancel()
            try:
                await asyncio.wait_for(self._agent_task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        if self._mcp_manager:
            try:
                await self._mcp_manager.stop()
            except Exception:
                pass
        try:
            await self._chrome_bridge.stop()
        except Exception:
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
        try:
            self._log_action_line("[session] action log closed")
            self._action_log_handle.close()
        except Exception:
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

    async def get_network_approval(self, request_id: str, url: str, domain: str, tool_name: str = "") -> bool:
        """Return True if the user approves network access to *domain*.

        Skips the prompt if *domain* was already session-approved.
        """
        if not self._network_policy.needs_approval(url):
            return True
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._pending_network_approvals[request_id] = fut
        from bob.protocol.events import Event, NetworkApprovalRequestedEvent
        await self._emit(Event(
            id="network",
            msg=NetworkApprovalRequestedEvent(
                url=url,
                domain=domain,
                tool_name=tool_name,
                request_id=request_id,
            )
        ))
        try:
            result = await fut
            if result.get("approve_always"):
                self._network_policy.approve_domain(domain, session_only=True)
            return result.get("approved", False)
        finally:
            self._pending_network_approvals.pop(request_id, None)

    async def request_dynamic_tool(
        self,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        timeout_seconds: float = 120.0,
        max_retries: int = 1,
        max_output_chars: int = 32_000,
    ) -> str:
        """Emit a dynamic tool call event and wait for a response op."""
        from bob.protocol.events import DynamicToolCallEvent

        timeout_seconds = max(1.0, min(float(timeout_seconds), 900.0))
        retries = max(0, min(int(max_retries), 5))
        capped_output = max(256, min(int(max_output_chars), 100_000))

        import json

        try:
            input_payload = json.dumps(tool_input, ensure_ascii=True, default=str)
        except Exception as exc:
            return f"Error: dynamic tool '{tool_name}' input is not JSON serializable: {exc}"
        if len(input_payload) > 64_000:
            return (
                f"Error: dynamic tool '{tool_name}' input too large "
                f"({len(input_payload)} chars, max 64000)."
            )

        async def _await_once() -> str:
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            self._pending_dynamic_tool_calls[tool_call_id] = fut
            await self._emit(Event(
                id=tool_call_id,
                msg=DynamicToolCallEvent(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                ),
            ))
            try:
                result = await asyncio.wait_for(fut, timeout=timeout_seconds)
                if isinstance(result, str):
                    text = result
                else:
                    try:
                        text = json.dumps(result, ensure_ascii=False)
                    except Exception:
                        text = str(result)
                if len(text) > capped_output:
                    return text[:capped_output] + "\n... [dynamic output truncated]"
                return text
            finally:
                self._pending_dynamic_tool_calls.pop(tool_call_id, None)

        for attempt in range(retries + 1):
            try:
                return await _await_once()
            except asyncio.TimeoutError:
                if attempt < retries:
                    continue
                return (
                    f"Error: dynamic tool '{tool_name}' timed out after "
                    f"{int(timeout_seconds * 1000)}ms waiting for response."
                )
        return f"Error: dynamic tool '{tool_name}' failed unexpectedly."

    def resolve_dynamic_tool(self, tool_call_id: str, result: Any) -> bool:
        fut = self._pending_dynamic_tool_calls.get(tool_call_id)
        if fut is None or fut.done():
            return False
        fut.set_result(result)
        return True

    # ------------------------------------------------------------------
    # Agent loop
    # ------------------------------------------------------------------

    async def _agent_loop(self) -> None:
        """Main agent loop: process submissions, run turns, route approval ops."""
        from bob.core.turn import run_turn
        from bob.protocol.ops import (
            UserTurnOp, InterruptOp, ExecApprovalOp, PatchApprovalOp,
            NetworkApprovalOp,
            DynamicToolResponseOp, UserInputAnswerOp,
            CompactOp, ShutdownOp, SetThreadNameOp, RunUserShellCommandOp,
            OverrideTurnContextOp, ThreadRollbackOp, UndoOp,
            DropMemoriesOp, UpdateMemoriesOp,
            ListMcpToolsOp, RefreshMcpServersOp, ListSkillsOp,
        )
        from bob.protocol.events import (
            SessionEndedEvent, ThreadNameSetEvent,
            UndoCompletedEvent, ThreadRollbackCompletedEvent,
        )

        current_turn_task: Optional[asyncio.Task] = None
        current_turn_preview = ""

        while not self._shutdown_event.is_set():
            try:
                submission = await asyncio.wait_for(self._sq.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            op = submission.op
            sub_id = submission.id

            if current_turn_task is not None and current_turn_task.done():
                try:
                    exc = current_turn_task.exception()
                    if exc is not None:
                        from bob.protocol.events import ErrorEvent
                        await self._emit(Event(
                            id=sub_id,
                            msg=ErrorEvent(type="error", message=str(exc))
                        ))
                except asyncio.CancelledError:
                    pass
                finally:
                    if current_turn_preview:
                        await self._touch_session_activity(current_turn_preview, turn_completed=True)
                    current_turn_preview = ""
                    current_turn_task = None
                    self._current_turn_cancel = None

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

            if isinstance(op, NetworkApprovalOp):
                fut = self._pending_network_approvals.get(op.request_id)
                if fut and not fut.done():
                    fut.set_result({
                        "approved": op.approved,
                        "approve_always": op.approve_always,
                    })
                continue

            if isinstance(op, DynamicToolResponseOp):
                self.resolve_dynamic_tool(op.tool_call_id, op.result)
                continue

            # ----------------------------------------------------------------
            # Plan approval (from exit_plan_mode tool)
            # ----------------------------------------------------------------
            from bob.protocol.ops import PlanApprovalOp
            if isinstance(op, PlanApprovalOp):
                if op.approved:
                    self._plan_mode = False
                    from bob.protocol.events import PlanApprovedEvent
                    await self._emit(Event(
                        id=sub_id,
                        msg=PlanApprovedEvent(type="plan_approved")
                    ))
                else:
                    # Stay in plan mode
                    from bob.protocol.events import PlanRejectedEvent
                    await self._emit(Event(
                        id=sub_id,
                        msg=PlanRejectedEvent(type="plan_rejected", reason=op.feedback)
                    ))
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
                await self.compact_history(
                    reason="manual",
                    sub_id=sub_id,
                    hint=op.hint,
                )
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
                if self._recorder:
                    await self._recorder.write({
                        "type": "thread_rolled_back",
                        "num_turns": n,
                    })
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
                if self._recorder:
                    await self._recorder.write({
                        "type": "thread_rolled_back",
                        "num_turns": 1,
                        "to_submission_id": op.to_submission_id,
                    })
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
            # List MCP tools
            # ----------------------------------------------------------------
            if isinstance(op, ListMcpToolsOp):
                from bob.protocol.events import McpToolsListedEvent
                tools = []
                if self._mcp_manager:
                    for t in self._mcp_manager.get_all_tools():
                        if op.server_name and t.server_name != op.server_name:
                            continue
                        tools.append({
                            "server_name": t.server_name,
                            "name": t.name,
                            "description": t.description,
                        })
                if not tools:
                    from bob.mcp.demo import list_demo_mcp_tools
                    tools = list_demo_mcp_tools(op.server_name)
                await self._emit(Event(
                    id=sub_id,
                    msg=McpToolsListedEvent(
                        type="mcp_tools_listed",
                        tools=tools,
                    )
                ))
                continue

            # ----------------------------------------------------------------
            # Refresh MCP servers
            # ----------------------------------------------------------------
            if isinstance(op, RefreshMcpServersOp):
                from bob.protocol.events import McpServersRefreshedEvent
                if self._mcp_manager:
                    await self._mcp_manager.stop()
                    self._mcp_manager = None
                # Unregister old MCP tools from registry
                self.tool_registry.unregister_by_source("mcp")
                await self._start_mcp()
                connected = self._mcp_manager.connected_servers() if self._mcp_manager else []
                failed = self._mcp_manager.failed_servers() if self._mcp_manager else []
                await self._emit(Event(
                    id=sub_id,
                    msg=McpServersRefreshedEvent(
                        type="mcp_servers_refreshed",
                        connected=connected,
                        failed=failed,
                    )
                ))
                continue

            # ----------------------------------------------------------------
            # List skills
            # ----------------------------------------------------------------
            if isinstance(op, ListSkillsOp):
                from bob.protocol.events import SkillsListedEvent
                from bob.protocol.items import SkillsListEntry
                entries = []
                if self._skills_manager:
                    cwd = Path(op.cwd) if op.cwd else self.cwd
                    discovered = self._skills_manager.discover(cwd=cwd, force_reload=True)
                    entries = [e.model_dump(mode="json") for e in discovered]
                if not entries:
                    from bob.skills.demo import list_demo_skill_entries
                    entries = [
                        e.model_dump(mode="json")
                        for e in list_demo_skill_entries()
                    ]
                await self._emit(Event(
                    id=sub_id,
                    msg=SkillsListedEvent(
                        type="skills_listed",
                        entries=entries,
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
            # User turn â€” the main path
            # ----------------------------------------------------------------
            if isinstance(op, UserTurnOp):
                if current_turn_task is not None and not current_turn_task.done():
                    from bob.protocol.events import ErrorEvent
                    await self._emit(Event(
                        id=sub_id,
                        msg=ErrorEvent(type="error", message="A turn is already running.")
                    ))
                    continue
                await self.manage_context_pre_turn(sub_id)
                user_preview = self._preview_from_user_turn(op)
                current_turn_preview = user_preview

                # Fire user_prompt_expansion before the turn reaches the model
                from bob.protocol.config_types import HookEventName
                asyncio.create_task(self.hook_runner.run_hooks(
                    HookEventName.USER_PROMPT_EXPANSION,
                    {"preview": user_preview[:500], "session_id": self.session_id},
                ))

                cancel_ev = asyncio.Event()
                self._current_turn_cancel = cancel_ev
                current_turn_task = asyncio.create_task(
                    run_turn(self, sub_id, op, cancel_ev)
                )
            else:
                continue  # op already handled earlier in the loop

            if current_turn_task is None:
                continue

            # Keep polling the submission queue while the turn is running so
            # approval and interrupt ops can resolve the futures the active
            # turn is waiting on.
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

                    elif isinstance(inner_op, NetworkApprovalOp):
                        fut = self._pending_network_approvals.get(inner_op.request_id)
                        if fut and not fut.done():
                            fut.set_result({
                                "approved": inner_op.approved,
                                "approve_always": inner_op.approve_always,
                            })
                        if inner_op.approve_always:
                            self._network_policy.approve_domain(inner_op.domain, session_only=True)

                    elif isinstance(inner_op, DynamicToolResponseOp):
                        self.resolve_dynamic_tool(inner_op.tool_call_id, inner_op.result)

                    elif isinstance(inner_op, UserInputAnswerOp):
                        fut = self._pending_user_inputs.get(inner_op.request_id)
                        if fut and not fut.done():
                            fut.set_result(inner_op.answer)

                    elif isinstance(inner_op, InterruptOp):
                        cancel_ev.set()

                exc = current_turn_task.exception()
                if exc is not None:
                    from bob.protocol.events import ErrorEvent
                    await self._emit(Event(
                        id=sub_id,
                        msg=ErrorEvent(type="error", message=str(exc))
                    ))
                    from bob.protocol.config_types import HookEventName
                    asyncio.create_task(self.hook_runner.run_hooks(
                        HookEventName.STOP_FAILURE,
                        {"error": str(exc), "session_id": self.session_id},
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
                await self._touch_session_activity(user_preview, turn_completed=True)

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
