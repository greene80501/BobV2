"""
bob terminal interface — inline chat UI mirroring Claude Code's visual style.

Output split:
  • Header  → rich.Panel  (printed BEFORE patch_stdout, so raw ANSI is fine)
  • Events  → print_formatted_text(ANSI(...))  inside patch_stdout — the only
              path that survives prompt_toolkit's Windows stdout proxy correctly

Main-loop contract
  • While _task_running the ❯ prompt is NEVER shown — prevents stray ❯ before
    approval prompts (Bug 1 / Bug 7 from comparison with Claude Code / Codex).
  • Approval events are handled inline with their own prompt.
  • _approval_event is cleared immediately after resolving a future (Bug 2).
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.patch_stdout import patch_stdout

from rich.console import Console

from bob.config.schema import BobConfig
from bob.tui.slash_commands import (
    AVAILABLE_DURING_TASK,
    COMMAND_DESCRIPTIONS,
    SlashCommand,
    fuzzy_match_commands,
    parse_command,
)


# ── Rich console — header only (before patch_stdout) ─────────────────────────

_con = Console(highlight=False, soft_wrap=True)


# ── ANSI helpers — ALL output inside patch_stdout uses these ──────────────────

_R   = "\033[0m"    # reset
_DIM = "\033[2m"    # dim
_BLD = "\033[1m"    # bold
_RED = ""   # red
_GRN = ""   # green
_YLW = ""   # yellow
_CYN = ""   # cyan
_PRP = "" # purple (#a46eff)
_BLU = ""   # blue (#0f62fe)


def _d(s: str) -> str:   return f"{_DIM}{s}{_R}"
def _b(s: str) -> str:   return f"{_BLD}{s}{_R}"
def _r(s: str) -> str:   return f"{_RED}{s}{_R}"
def _g(s: str) -> str:   return f"{_GRN}{s}{_R}"
def _y(s: str) -> str:   return f"{_YLW}{s}{_R}"
def _c(s: str) -> str:   return f"{_PRP}{s}{_R}"
def _cb(s: str) -> str:  return f"{_BLU}{_BLD}{s}{_R}"
def _cg(s: str) -> str:  return f"{_GRN}{s}{_R}"
def _bold(s: str) -> str: return f"{_BLD}{s}{_R}"



def _truncate_cmd(s: str, max_len: int = 120) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[:max_len - 1] + "…"


def _p(s: str = "", end: str = "\n") -> None:
    """Print ANSI text via prompt_toolkit — safe inside patch_stdout on all platforms."""
    print_formatted_text(ANSI(s + end), end="")


# ── Approval prompt string (shared between event consumer and main loop) ───────

_APPROVAL_PROMPT = ANSI(
    f"  {_d('[y]')} yes  "
    f"{_d('[a]')} always  "
    f"{_d('[n]')} no  "
    f"{_d('[s]')} skip  "
    f"› "
)


# ── Output collapsing ─────────────────────────────────────────────────────────

_EXEC_MAX_LINES = 5


def _collapse_lines(lines: list[str]) -> list[str]:
    """Fold long output: first N + last N lines with omitted count in between."""
    if len(lines) <= _EXEC_MAX_LINES * 2:
        return lines
    omitted = len(lines) - _EXEC_MAX_LINES * 2
    return (
        lines[:_EXEC_MAX_LINES]
        + [f"\x00DIM+{omitted} lines …"]   # sentinel; rendered dim in _print_tool_output
        + lines[-_EXEC_MAX_LINES:]
    )


# ── Slash completer ───────────────────────────────────────────────────────────

class _SlashCompleter(Completer):
    """Inline slash-command + model completer.

    Behaviour:
      /          → all commands alphabetically (multi-column grid)
      /mo        → fuzzy-filtered commands ("model", "mcp", …)
      /model     → all commands still, "model" highlighted
      /model     → (after space) model names from the catalog, filterable
      /effort    → effort levels: low / medium / high
      /approvals → approval policy values
    """

    task_running: bool = False

    # ── Argument completers for specific commands ─────────────────────────

    _EFFORT_LEVELS = ["high", "low", "medium"]
    _APPROVAL_VALUES = ["auto-edit", "full-auto", "on-failure", "on-request", "suggest"]
    _OUTPUT_STYLES = ["brief", "normal", "verbose"]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        # ── After a space: complete arguments for known commands ──────────
        space = text.find(" ")
        if space != -1:
            cmd_part = text[1:space].lower()
            arg_part = text[space + 1:]
            yield from self._complete_args(cmd_part, arg_part)
            return

        # ── No space yet: complete the command name itself ────────────────
        query = text[1:]

        if not query:
            # Just "/" typed — show ALL commands alphabetically
            cmds = sorted(
                [c for c in SlashCommand
                 if not self.task_running or c in AVAILABLE_DURING_TASK],
                key=lambda c: c.value,
            )
            for c in cmds:
                desc = COMMAND_DESCRIPTIONS.get(c, "")
                yield Completion(
                    c.value,
                    start_position=0,
                    display=c.value,
                    display_meta=desc,
                )
        else:
            # Partial input — fuzzy filter
            for m in fuzzy_match_commands(query, self.task_running):
                val  = m.command.value
                desc = COMMAND_DESCRIPTIONS.get(m.command, "")
                yield Completion(
                    val,
                    start_position=-len(query),
                    display=val,
                    display_meta=desc,
                )

    def _complete_args(self, cmd: str, arg: str):
        """Yield completions for the argument portion of a command."""
        q = arg.lower()

        if cmd == "model":
            yield from self._complete_model(arg)

        elif cmd == "effort":
            for level in self._EFFORT_LEVELS:
                if level.startswith(q):
                    meta = {"low": "faster & cheaper", "medium": "balanced",
                            "high": "most thorough"}[level]
                    yield Completion(level, start_position=-len(arg),
                                     display=level, display_meta=meta)

        elif cmd in ("approvals", "permissions"):
            for val in self._APPROVAL_VALUES:
                if q in val:
                    yield Completion(val, start_position=-len(arg), display=val)

        elif cmd == "output-style":
            for style in self._OUTPUT_STYLES:
                if style.startswith(q):
                    yield Completion(style, start_position=-len(arg), display=style)

    def _complete_model(self, query: str):
        """Yield model-name completions from the catalog."""
        try:
            from bob.llm.catalog import get_catalog
            catalog = get_catalog()
            if not catalog.is_populated():
                return
            if query:
                models = catalog.search_models(query)
            else:
                models = catalog.list_models(status="active")
            for m in models[:40]:
                mid      = m["model_id"]
                provider = m.get("provider") or ""
                ctx      = m.get("context_window")
                ctx_str  = f"{ctx // 1000}K" if ctx else ""
                inp      = m.get("input_price_per_1m")
                price    = f"${inp:.2f}/1M" if inp is not None else ""
                meta     = "  ".join(x for x in [provider, ctx_str, price] if x)
                yield Completion(
                    mid,
                    start_position=-len(query),
                    display=mid,
                    display_meta=meta,
                )
        except Exception:
            pass


# ── Spinner ───────────────────────────────────────────────────────────────────

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPINNER_LABEL  = "Thinking…"


# ── Interface ─────────────────────────────────────────────────────────────────

class Interface:
    def __init__(self, session, config: BobConfig) -> None:
        self._session = session
        self._config  = config
        self._task_running   = False
        self._last_assistant_text = ""
        self._current_buf    = ""
        self._text_started   = False
        self._after_tool     = False    # True right after ExecCompleted — skip blank before next tool header
        self._exec_output_buf: list[str] = []
        self._approved_ids: set[str] = set()
        # Approval coordination
        self._pending_approval: Optional[tuple] = None
        self._approval_event  = asyncio.Event()
        # Fired the moment TurnStartedEvent arrives — lets the ❯ prompt cancel fast
        self._turn_started    = asyncio.Event()
        self._done            = asyncio.Event()
        self._exit_requested  = asyncio.Event()
        # Spinner
        self._spinner_task:   Optional[asyncio.Task] = None
        self._spinner_stop:   Optional[asyncio.Event] = None
        self._spinner_active = False
        self._spinner_label: str = "Thinking…"
        # Token / cost tracking
        self._total_input_tokens  = 0
        self._total_output_tokens = 0
        self._total_cached_input_tokens = 0
        self._last_turn_tokens: dict = {}
        # Context items prepended to next user turn
        self._pending_context_items: list[str] = []
        # Output style
        self._output_style: str = "normal"
        # VI mode
        self._vi_mode: bool = False
        self._vi_mode_changed: bool = False
        # Extended thinking
        self._next_turn_thinking_budget: Optional[int] = None

    # ── Dynamic prompt ────────────────────────────────────────────────────────

    def _prompt_str(self) -> ANSI:
        """❯ — never shown while task is running (main loop guards this)."""
        return ANSI("❯ ")

    async def _save_config(self):
        """Save current config to ~/.bob/config.toml"""
        import toml
        from pathlib import Path
        
        config_path = Path.home() / ".bob" / "config.toml"
        
        # Convert config to dict
        config_dict = self._config.dict()
        
        # Write to file
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as f:
                toml.dump(config_dict, f)
        except Exception as exc:
            _p(f"  {_y('⚠')} Failed to save config: {exc}")

    # ── Header — Claude Code-style welcome panel ──────────────────────────────

    def _print_header(self) -> None:
        """Print the welcome header directly to sys.__stdout__ before patch_stdout."""
        bob_version = "0.1.0"
        try:
            from bob import __version__
            bob_version = __version__
        except Exception:
            bob_version = "0.1.0"

        term_w = shutil.get_terminal_size((120, 24)).columns
        inner_w = term_w - 4 # excluding the very outer frame chars (│  │)

        # Divvy up the columns.
        # Mascot block requires ~30 inner chars minimum, 50 is safe
        CENTER_W = 50
        LEFT_W = 42 # sufficient for System info width
        RIGHT_W = inner_w - LEFT_W - CENTER_W - 6 # accounting for two inner " │ " dividers 

        # ANSI helpers
        RST   = "\033[0m"
        DIM   = "\033[2m"
        BOLD  = "\033[1m"
        BRAND = "" # monochrome

        def vlen(s: str) -> int:
            import re
            return len(re.sub(r"\033\[[0-9;]*m", "", s))

        def center(s: str, w: int) -> str:
            v = vlen(s)
            if v >= w: return s
            pl = (w - v) // 2
            pr = w - v - pl
            return " " * pl + s + " " * pr

        def rpad(s: str, w: int) -> str:
            v = vlen(s)
            return s if v >= w else s + " " * (w - v)

        # Mascot (Unicode block chars, exact copy of bobart2.md, custom 10-line size)
        mascot = [
            f"{BRAND}⠀⠀⢀⣠⣴⣿⣿⣿⣷⣦⣀⠀⠀⠀{RST}",
            f"{BRAND}⠀⢠⣾⣿⣿⣿⣿⣿⣿⣿⣿⣦⠀⠀{RST}",
            f"{BRAND}⢀⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣇⡀{RST}",
            f"{BRAND}⣻⣿⠿⢿⣿⠿⠿⠿⢿⣿⠿⢷⣾⡃{RST}",
            f"{BRAND}⣿⣿⠀⢿⣿⡇⠀⠐⣿⣿⠆⢸⣿⡇{RST}",
            f"{BRAND}⠉⢻⣄⣀⣀⣒⣶⣖⣂⣀⣀⣼⠋⠁{RST}",
            f"{BRAND}⠀⢠⡞⢿⡟⠛⣛⡛⠛⣿⡟⣶⠀⠀{RST}",
            f"{BRAND}⠀⣸⣧⣼⣷⡺⠿⠽⣢⣿⣧⣼⡀⠀{RST}",
            f"{BRAND}⢰⣯⣤⣬⣯⡙⠛⠛⣹⣯⣤⣬⣷⠀{RST}",
            f"{BRAND}⠀⠀⣾⣿⣿⣿⡆⣾⣿⣿⣿⡆⠀⠀{RST}",
        ]

        import os
        import pathlib
        model = self._config.model or "unknown"
        sandbox = self._config.sandbox_mode.value if self._config.sandbox_mode else "none"
        cwd_str = str(self._config.exec_cwd or os.getcwd())
        
        # Abbreviate home
        try:
            home = str(pathlib.Path.home())
            if cwd_str.startswith(home):
                cwd_str = "~" + cwd_str[len(home):]
            if len(cwd_str) > 23:
                cwd_str = "..." + cwd_str[-20:]
        except Exception:
            pass

        # Left Column: System Info
        left_rows = [
            "",
            f"  {BOLD}System Info{RST}",
            f"  {DIM}Model:    {model}{RST}",
            f"  {DIM}Workspace: {sandbox}{RST}",
            f"  {DIM}System:    Bob v2{RST}",
            f"  {DIM}Directory: {cwd_str}{RST}",
            ""
        ]

        # Right Column: Tips & Basic Commands
        right_rows = [
            f"  {BOLD}Tips & Basic Commands{RST}",
            f"  {DIM}Bob is an AI assistant that can write code and run commands.{RST}",
            f"  {DIM}• /help   - View all available commands{RST}",
            f"  {DIM}• /init   - Initialize configuration and AGENTS.md{RST}",
            f"  {DIM}• /skills - Manage and teach bob new capabilities{RST}",
            f"  {DIM}• /exit   - Shut down correctly safely{RST}"
        ]

        # Divvy up the columns dynamically based on actual content lengths!
        LEFT_W = max([vlen(l) for l in left_rows])
        RIGHT_W = max([vlen(r) for r in right_rows])
        CENTER_W = inner_w - LEFT_W - RIGHT_W - 6 # accounting for two inner "   " dividers 

        # Center Column: Mascot and Welcome
        center_rows = [
            center(f"{BRAND}Welcome to bob!{RST}", CENTER_W),
            "",
        ] + [center(row, CENTER_W) for row in mascot]

        # Ensure same number of rows
        n = max(len(left_rows), len(center_rows), len(right_rows))
        while len(left_rows) < n: left_rows.append("")
        while len(center_rows) < n: center_rows.append("")
        while len(right_rows) < n: right_rows.append("")

        title  = f"bob v{bob_version}"
        ndash  = max(0, term_w - 5 - len(title) - 2)
        top    = f"╭─── {title} {'─' * ndash}╮"
        bot    = "╰" + "─" * (term_w - 2) + "╯"

        import sys
        out = sys.__stdout__
        out.write("\n" + top + "\n")
        
        for l, c, r in zip(left_rows, center_rows, right_rows):
            # 3 Columns with gentle spacing, dropping interior borders entirely to look floating
            out.write(f"│ {rpad(l, LEFT_W)}   {center(c, CENTER_W)}   {rpad(r, RIGHT_W)} │\n")
            
        out.write(bot + "\n\n")
        out.flush()

    # ── Spinner ───────────────────────────────────────────────────────────────

    async def _start_spinner(self) -> None:
        self._spinner_stop   = asyncio.Event()
        self._spinner_active = True
        self._spinner_task   = asyncio.create_task(self._run_spinner())

    async def _stop_spinner(self) -> None:
        if not self._spinner_active:
            return
        self._spinner_active = False
        if self._spinner_stop:
            self._spinner_stop.set()
        if self._spinner_task and not self._spinner_task.done():
            try:
                await asyncio.wait_for(self._spinner_task, timeout=0.3)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                self._spinner_task.cancel()
        self._spinner_task = None

    async def _run_spinner(self) -> None:
        """Animate via sys.__stdout__ (bypasses patch_stdout proxy so \\r works)."""
        out    = sys.__stdout__
        frames = _SPINNER_FRAMES
        i = 0
        try:
            while not self._spinner_stop.is_set():
                frame = frames[i % len(frames)]
                label = self._spinner_label
                width = len(label) + 6
                out.write(f"\r  {frame} \033[2m{label}\033[0m")
                out.flush()
                i += 1
                await asyncio.sleep(0.08)
        finally:
            # Clear with max possible width
            out.write("\r" + " " * 80 + "\r")
            out.flush()

    # ── Tool-call block helpers ───────────────────────────────────────────────

    @staticmethod
    def _format_command(command: list[str]) -> tuple[str, str]:
        """
        Return (tool_label, arg_string) for display.

        Rules:
        - apply_patch  → ("Patch", "file1, file2") extracted from patch text
        - cmd.exe /C … → ("Bash", inner command)
        - powershell … → ("Bash", inner command, stripped of -Command flag)
        - everything else → ("Bash", joined command, truncated to 120 chars)
        """
        if not command:
            return "Bash", ""

        cmd0 = command[0].lower()

        # apply_patch: extract filenames from patch text
        if command[0] == "apply_patch":
            patch = command[1] if len(command) > 1 else ""
            files = []
            for line in patch.splitlines():
                for prefix in ("*** Add File: ", "*** Update File: ", "*** Delete File: "):
                    if line.startswith(prefix):
                        files.append(line[len(prefix):].strip())
            label = "Patch"
            arg = ", ".join(files) if files else "…"
            return label, arg

        # cmd.exe /C <rest>: strip wrapper, show inner command
        if cmd0 in ("cmd.exe", "cmd") and len(command) >= 3 and command[1].upper() == "/C":
            inner = " ".join(command[2:])
            return "Bash", _truncate_cmd(inner)

        # powershell: strip powershell.exe/-Command/-c flags
        if "powershell" in cmd0:
            parts = command[1:]
            # Drop -Command / -c / -NonInteractive / -NoProfile etc.
            cleaned = [p for p in parts if not p.startswith("-")]
            inner = " ".join(cleaned).strip() or " ".join(parts)
            return "Bash", _truncate_cmd(inner)

        # Everything else
        return "Bash", _truncate_cmd(" ".join(command))

    def _print_tool_header(self, tool: str, arg: str, suffix: str = "") -> None:
        """  ● Tool(arg) [suffix]"""
        suf = f"  {_d(suffix)}" if suffix else ""
        _p(f"  {_c('●')} {_b(tool)}({_c(arg)}){suf}")

    def _colorize_diff_line(self, line: str) -> str:
        """Colorize a single diff line: + green, - red, @@ cyan."""
        stripped = line.lstrip()
        if stripped.startswith("+++") or stripped.startswith("---"):
            return _d(line)  # file headers dim
        elif stripped.startswith("+"):
            return _g(line)  # additions green
        elif stripped.startswith("-"):
            return _r(line)  # deletions red
        elif stripped.startswith("@@"):
            return _c(line)  # hunk headers cyan/purple
        elif stripped.startswith("***"):
            return _c(line)  # patch file markers cyan
        return line

    def _print_tool_output(self, lines: list[str], colorize_diff: bool = False) -> None:
        """⎿ on first output line, indent on rest, dim for collapsed-count sentinel."""
        for i, line in enumerate(lines):
            if line.startswith("\x00DIM"):        # collapsed count sentinel
                _p(f"     {_d(line[4:])}")
                continue
            prefix = "  ⎿ " if i == 0 else "     "
            if colorize_diff:
                line = self._colorize_diff_line(line)
            _p(f"{prefix}{line}")

    # ── Event consumer ────────────────────────────────────────────────────────

    async def _consume_events(self) -> None:  # noqa: C901
        from bob.protocol.events import (
            BackgroundTerminalOutputEvent,
            ErrorEvent,
            ExecApprovalRequestedEvent,
            ExecCompletedEvent,
            ExecOutputEvent,
            ExecStartedEvent,
            InfoEvent,
            PatchApprovalRequestedEvent,
            PlanApprovalRequestedEvent,
            PlanApprovedEvent,
            PlanRejectedEvent,
            ReasoningDeltaEvent,
            SessionEndedEvent,
            TextDeltaEvent,
            TurnEndedEvent,
            TurnInterruptedEvent,
            TurnStartedEvent,
            WarningEvent,
        )
        try:
            from bob.protocol.events import UserInputRequestEvent
            _has_user_input_event = True
        except ImportError:
            _has_user_input_event = False
            UserInputRequestEvent = None

        async for event in self._session.events():
            msg = event.msg
            try:
                # ── Turn lifecycle ────────────────────────────────────────────

                if isinstance(msg, TurnStartedEvent):
                    self._task_running = True
                    self._turn_started.set()   # unblocks ❯ prompt immediately
                    self._current_buf  = ""
                    self._text_started = False
                    self._after_tool   = False
                    # Spinner is started by _busy_wait AFTER the ❯ prompt is
                    # fully torn down — do NOT start it here.

                # ── Streaming text ────────────────────────────────────────────

                elif isinstance(msg, TextDeltaEvent):
                    if not self._text_started:
                        await self._stop_spinner()
                        self._text_started = True
                        # blank line separating tool output from AI prose
                        if self._after_tool:
                            _p()
                        self._after_tool = False
                        _p("• ", end="")
                    # Print delta immediately for real-time streaming
                    _p(msg.delta, end="")
                    # Also accumulate for markdown rendering at turn end
                    self._current_buf += msg.delta

                # ── Extended thinking ─────────────────────────────────────────

                elif isinstance(msg, ReasoningDeltaEvent):
                    if not hasattr(self, '_reasoning_started') or not self._reasoning_started:
                        await self._stop_spinner()
                        self._reasoning_started = True
                        if self._after_tool:
                            _p()
                        self._after_tool = False
                        # Start reasoning block with thinking icon
                        _p(f"{_d('💭 thinking...')}")
                        self._reasoning_buf = ""
                    # Accumulate reasoning silently - will be displayed at end
                    self._reasoning_buf += msg.delta

                # ── Command execution ─────────────────────────────────────────

                elif isinstance(msg, ExecStartedEvent):
                    await self._stop_spinner()
                    if self._current_buf and not self._current_buf.endswith("\n"):
                        _p()
                    self._current_buf     = ""
                    self._exec_output_buf = []
                    # Track if this is apply_patch for diff colorization
                    self._is_apply_patch = (msg.command and msg.command[0] == "apply_patch")
                    if msg.tool_call_id not in self._approved_ids:
                        tool_label, cmd_arg = self._format_command(msg.command)
                        # Update spinner label to show tool name
                        self._spinner_label = f"Running {tool_label}…"
                        # blank line before tool header only when following prose
                        if not self._after_tool:
                            _p()
                        self._print_tool_header(tool_label, cmd_arg)
                        self._after_tool = False
                        # Start spinner to show tool execution
                        await self._start_spinner()
                    else:
                        self._approved_ids.discard(msg.tool_call_id)

                elif isinstance(msg, ExecOutputEvent):
                    self._exec_output_buf.extend(msg.data.splitlines())

                elif isinstance(msg, ExecCompletedEvent):
                    await self._stop_spinner()
                    # Reset spinner label to default
                    self._spinner_label = "Thinking…"
                    colorize = getattr(self, '_is_apply_patch', False)
                    self._print_tool_output(_collapse_lines(self._exec_output_buf), colorize_diff=colorize)
                    self._exec_output_buf = []
                    self._is_apply_patch = False
                    code = msg.exit_code
                    ms   = msg.duration_ms
                    if code != 0:
                        # exit code is metadata, not output — 5-space indent, no ⎿
                        _p(f"     {_r(f'exit {code}')}{_d(f'  ·  {ms}ms')}")
                    self._after_tool = True
                    # No blank line here — let the NEXT event decide spacing

                # ── Approval — exec ───────────────────────────────────────────

                elif isinstance(msg, ExecApprovalRequestedEvent):
                    await self._stop_spinner()
                    if self._current_buf and not self._current_buf.endswith("\n"):
                        _p()
                    self._current_buf = ""
                    if not self._task_running:
                        self._task_running = True
                    tool_label, cmd_arg = self._format_command(msg.command)
                    if not self._after_tool:
                        _p()
                    self._print_tool_header(tool_label, cmd_arg, suffix="· needs approval")
                    self._after_tool = False
                    fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
                    self._pending_approval = (msg, fut)
                    self._approval_event.set()
                    decision_str = await fut
                    # Clear immediately so main loop doesn't pick up the stale event
                    self._approval_event.clear()
                    self._pending_approval = None
                    from bob.protocol.config_types import ReviewDecision
                    from bob.protocol.ops import ExecApprovalOp
                    _map = {
                        "y": ReviewDecision.APPROVED,
                        "yes": ReviewDecision.APPROVED,
                        "a": ReviewDecision.APPROVED_FOR_SESSION,
                        "always": ReviewDecision.APPROVED_FOR_SESSION,
                        "n": ReviewDecision.DENIED,
                        "no": ReviewDecision.DENIED,
                        "s": ReviewDecision.ABORT,
                        "skip": ReviewDecision.ABORT,
                    }
                    decision = _map.get(decision_str, ReviewDecision.DENIED)
                    if decision in (ReviewDecision.APPROVED, ReviewDecision.APPROVED_FOR_SESSION):
                        self._approved_ids.add(msg.tool_call_id)
                    await self._session.submit(
                        ExecApprovalOp(tool_call_id=msg.tool_call_id, decision=decision)
                    )

                # ── Approval — patch ──────────────────────────────────────────

                elif isinstance(msg, PatchApprovalRequestedEvent):
                    await self._stop_spinner()
                    if not self._task_running:
                        self._task_running = True
                    n = len(msg.changes)
                    if not self._after_tool:
                        _p()
                    self._print_tool_header("Patch", f"{n} file(s)", suffix="· needs approval")
                    # Show which files will be changed
                    for change in msg.changes:
                        path = getattr(change, "path", None) or getattr(change, "file", "?")
                        _p(f"     {_d(str(path))}")
                    self._after_tool = False
                    fut = asyncio.get_running_loop().create_future()
                    self._pending_approval = (msg, fut)
                    self._approval_event.set()
                    decision_str = await fut
                    self._approval_event.clear()
                    self._pending_approval = None
                    from bob.protocol.config_types import ReviewDecision
                    from bob.protocol.ops import PatchApprovalOp
                    _map = {
                        "y": ReviewDecision.APPROVED,
                        "yes": ReviewDecision.APPROVED,
                        "a": ReviewDecision.APPROVED_FOR_SESSION,
                        "n": ReviewDecision.DENIED,
                        "no": ReviewDecision.DENIED,
                        "s": ReviewDecision.ABORT,
                    }
                    await self._session.submit(
                        PatchApprovalOp(
                            tool_call_id=msg.tool_call_id,
                            decision=_map.get(decision_str, ReviewDecision.DENIED),
                        )
                    )

                # ── Turn end ──────────────────────────────────────────────────

                elif isinstance(msg, TurnEndedEvent):
                    await self._stop_spinner()
                    
                    # Display reasoning block if we have thinking content
                    if hasattr(self, '_reasoning_buf') and self._reasoning_buf:
                        lines = self._reasoning_buf.splitlines()
                        if len(lines) <= 10:
                            # Short reasoning - show all
                            _p(f"{_d('💭 Extended Thinking:')}")
                            for line in lines:
                                _p(f"{_d('  ')}{_d(line)}")
                        else:
                            # Long reasoning - show first 5 and last 5 with "..." in between
                            _p(f"{_d('💭 Extended Thinking:')}")
                            for line in lines[:5]:
                                _p(f"{_d('  ')}{_d(line)}")
                            _p(f"{_d('  ... ')}{_d(f'({len(lines) - 10} more lines)')}")
                            for line in lines[-5:]:
                                _p(f"{_d('  ')}{_d(line)}")
                        _p()  # Blank line after reasoning
                        self._reasoning_buf = ""
                        self._reasoning_started = False
                    
                    # Render accumulated markdown if we have text
                    if self._current_buf:
                        # Clear the raw text line
                        if not self._current_buf.endswith("\n"):
                            _p()
                        # Re-render with markdown formatting
                        try:
                            from rich.markdown import Markdown
                            from rich.console import Console
                            import io
                            
                            # Capture rich output to string
                            string_io = io.StringIO()
                            console = Console(file=string_io, force_terminal=True, width=shutil.get_terminal_size((120, 24)).columns - 4)
                            md = Markdown(self._current_buf)
                            console.print(md)
                            rendered = string_io.getvalue()
                            
                            # Print the rendered markdown
                            for line in rendered.splitlines():
                                _p(f"  {line}")
                        except Exception:
                            # Fallback to raw text if markdown rendering fails
                            if not self._current_buf.endswith("\n"):
                                _p()
                    elif self._after_tool and not self._current_buf:
                        # Turn ended with only tool calls and no prose — add spacing
                        _p()
                    
                    self._last_assistant_text = self._current_buf
                    self._current_buf  = ""
                    self._after_tool   = False
                    self._task_running = False
                    # Token tracking
                    in_tok  = getattr(msg, "input_tokens",  0) or 0
                    out_tok = getattr(msg, "output_tokens", 0) or 0
                    cached_tok = getattr(msg, "cached_input_tokens", 0) or 0
                    self._total_input_tokens  += in_tok
                    self._total_output_tokens += out_tok
                    self._total_cached_input_tokens += cached_tok
                    self._last_turn_tokens = {"input": in_tok, "output": out_tok, "cached": cached_tok}
                    
                    # Display token/cost status line
                    if hasattr(self._session, 'analytics') and self._session.analytics:
                        try:
                            from bob.llm.catalog import get_catalog
                            catalog = get_catalog()
                            ctx_window = catalog.get_context_window(self._config.model) if catalog.is_populated() else None
                            status = self._session.analytics.format_last_turn_status(
                                model=self._config.model,
                                context_window=ctx_window
                            )
                            if status:
                                _p(f"  {_d(status)}")
                        except Exception:
                            pass
                    
                    _p()   # one blank line = turn boundary (❯ adds visual separation)

                elif isinstance(msg, TurnInterruptedEvent):
                    await self._stop_spinner()
                    if self._current_buf and not self._current_buf.endswith("\n"):
                        _p()
                    self._current_buf  = ""
                    self._after_tool   = False
                    self._task_running = False
                    _p(f"  {_y('⚠')} interrupted")
                    _p()

                # ── Error / warning / info ────────────────────────────────────

                elif isinstance(msg, ErrorEvent):
                    await self._stop_spinner()
                    if self._current_buf and not self._current_buf.endswith("\n"):
                        _p()
                    self._current_buf  = ""
                    self._after_tool   = False
                    self._task_running = False
                    _p(f"  {_r('✗')} {msg.message}")
                    _p()

                elif isinstance(msg, WarningEvent):
                    _p(f"  {_y('⚠')} {msg.message}")

                elif isinstance(msg, InfoEvent):
                    _p(f"  {_d(msg.message)}")

                elif isinstance(msg, BackgroundTerminalOutputEvent):
                    _p(f"  {_d(f'[bg:{msg.terminal_id}] {msg.data.rstrip()}')}")

                elif UserInputRequestEvent is not None and isinstance(msg, UserInputRequestEvent):
                    await self._stop_spinner()
                    _p()
                    
                    # Distinct visual style for questions
                    _p(f"  {_cb('❓')} {_bold('Question from Bob:')}")
                    _p(f"  {_d('│')}")
                    
                    # Word-wrap the prompt at terminal width
                    import shutil
                    import textwrap
                    term_width = shutil.get_terminal_size().columns
                    wrapped_lines = textwrap.wrap(msg.prompt, width=term_width - 6)
                    for line in wrapped_lines:
                        _p(f"  {_d('│')} {line}")
                    _p(f"  {_d('└─')}")
                    _p()
                    
                    # Handle structured fields if present
                    if hasattr(msg, 'fields') and msg.fields:
                        import json
                        answers = {}
                        for field in msg.fields:
                            field_type = field.get('type', 'text')
                            label = field.get('label', field.get('name', ''))
                            
                            if field_type == 'boolean':
                                _p(f"  {label} (y/n): ", end="")
                                ps_tmp = PromptSession()
                                answer = await ps_tmp.prompt_async("")
                                answers[field['name']] = answer.lower() in ('y', 'yes', 'true', '1')
                            
                            elif field_type == 'select':
                                options = field.get('options', [])
                                _p(f"  {label}")
                                for i, opt in enumerate(options, 1):
                                    _p(f"    {i}. {opt}")
                                ps_tmp = PromptSession()
                                answer = await ps_tmp.prompt_async(f"  Select (1-{len(options)}): ")
                                try:
                                    idx = int(answer) - 1
                                    answers[field['name']] = options[idx] if 0 <= idx < len(options) else ""
                                except ValueError:
                                    answers[field['name']] = ""
                            
                            else:  # text
                                ps_tmp = PromptSession()
                                answer = await ps_tmp.prompt_async(f"  {label}: ")
                                answers[field['name']] = answer
                        
                        # Format as JSON for structured response
                        answer = json.dumps(answers)
                    else:
                        # Simple text input with custom prompt style
                        try:
                            ps_tmp = PromptSession()
                            answer = await ps_tmp.prompt_async(ANSI(f"  {_cg('›')} "))
                        except (EOFError, KeyboardInterrupt):
                            answer = ""
                    
                    from bob.protocol.ops import UserInputAnswerOp
                    await self._session.submit(
                        UserInputAnswerOp(request_id=msg.request_id, answer=answer)
                    )
                    if self._task_running and not self._spinner_active:
                        await self._start_spinner()

                elif isinstance(msg, SessionEndedEvent):
                    pass  # Session ended, no action needed

                elif isinstance(msg, PlanApprovalRequestedEvent):
                    await self._stop_spinner()
                    _p()
                    _p(f"  {_cy('📋')} {_bold('Plan Summary:')}")
                    _p(f"  {_d('┌─────────────────────────────────────')}")
                    
                    # Word-wrap and display plan
                    import shutil
                    import textwrap
                    term_width = shutil.get_terminal_size().columns
                    wrapped_lines = textwrap.wrap(msg.plan_summary, width=term_width - 6)
                    for line in wrapped_lines:
                        _p(f"  {_d('│')} {line}")
                    
                    _p(f"  {_d('└─────────────────────────────────────')}")
                    _p()
                    _p(f"  {_y('⚠')} This plan will unlock write tools and allow file modifications.")
                    _p()
                    
                    # Prompt for approval
                    try:
                        ps_tmp = PromptSession()
                        response = await ps_tmp.prompt_async(
                            ANSI(f"  Approve this plan? (y/n/feedback): ")
                        )
                    except (EOFError, KeyboardInterrupt):
                        response = "n"
                    
                    response = response.strip().lower()
                    
                    if response in ('y', 'yes'):
                        from bob.protocol.ops import PlanApprovalOp
                        await self._session.submit(PlanApprovalOp(approved=True))
                        _p(f"  {_g('✓')} Plan approved")
                    elif response in ('n', 'no'):
                        from bob.protocol.ops import PlanApprovalOp
                        await self._session.submit(PlanApprovalOp(approved=False))
                        _p(f"  {_r('✗')} Plan rejected")
                    else:
                        # Treat as feedback
                        from bob.protocol.ops import PlanApprovalOp
                        await self._session.submit(
                            PlanApprovalOp(approved=False, feedback=response)
                        )
                        _p(f"  {_y('⚠')} Plan rejected with feedback")
                    
                    _p()
                    if self._task_running and not self._spinner_active:
                        await self._start_spinner()

                elif isinstance(msg, PlanApprovedEvent):
                    _p(f"  {_g('✓')} Full tool access restored")

                elif isinstance(msg, PlanRejectedEvent):
                    if msg.reason:
                        _p(f"  {_y('⚠')} Staying in plan mode. Feedback: {msg.reason}")
                    else:
                        _p(f"  {_y('⚠')} Staying in plan mode")


                    self._done.set()
                    return

            except Exception:
                pass

    # ── Quick model turn (used by /commit, /summary, /review) ────────────────

    async def _quick_model_turn(self, prompt: str) -> str:
        """Submit a single user turn and return the accumulated response text.

        Safe to call inside a slash command handler — sets _task_running,
        drains events until TurnEndedEvent, then returns.
        """
        from bob.protocol.items import TextUserInput
        from bob.protocol.ops import UserTurnOp
        from bob.protocol.events import (
            TextDeltaEvent, TurnEndedEvent, TurnInterruptedEvent,
            ErrorEvent, SessionEndedEvent,
        )

        self._task_running = True
        await self._start_spinner()
        await self._session.submit(
            UserTurnOp(items=[TextUserInput(type="text", text=prompt)])
        )

        result_parts: list[str] = []
        async for event in self._session.events():
            msg = event.msg
            if isinstance(msg, TextDeltaEvent):
                await self._stop_spinner()
                if not result_parts:
                    _p("• ", end="")
                _p(msg.delta, end="")
                result_parts.append(msg.delta)
            elif isinstance(msg, TurnEndedEvent):
                if result_parts and not "".join(result_parts).endswith("\n"):
                    _p()
                in_tok  = getattr(msg, "input_tokens",  0) or 0
                out_tok = getattr(msg, "output_tokens", 0) or 0
                cached_tok = getattr(msg, "cached_input_tokens", 0) or 0
                self._total_input_tokens  += in_tok
                self._total_output_tokens += out_tok
                self._total_cached_input_tokens += cached_tok
                self._last_turn_tokens = {"input": in_tok, "output": out_tok, "cached": cached_tok}
                break
            elif isinstance(msg, (TurnInterruptedEvent, ErrorEvent, SessionEndedEvent)):
                break

        await self._stop_spinner()
        self._task_running = False
        return "".join(result_parts)

    # ── Slash dispatch ────────────────────────────────────────────────────────

    async def _dispatch_slash(self, cmd: SlashCommand, args: str) -> bool:
        """Handle a slash command. Returns True to exit the chat loop."""

        if cmd in (SlashCommand.QUIT, SlashCommand.EXIT):
            _p(f"  {_d('goodbye')}")
            return True

        elif cmd == SlashCommand.CLEAR:
            os.system("cls" if sys.platform == "win32" else "clear")
            self._print_header()

        elif cmd == SlashCommand.NEW:
            _p(f"  {_d('starting new chat…')}")
            await self._session.reset()
            _p()

        elif cmd == SlashCommand.COMPACT:
            _p(f"  {_d('compacting context…')}")
            from bob.protocol.ops import CompactOp
            await self._session.submit(CompactOp())

        elif cmd == SlashCommand.DIFF:
            try:
                result = subprocess.run(
                    ["git", "diff", "HEAD"],
                    capture_output=True, text=True, cwd=Path.cwd(), timeout=5,
                )
                out = result.stdout or result.stderr or "(no changes)"
                if out.strip():
                    _p()
                    for line in out.splitlines():
                        _p(f"  {self._colorize_diff_line(line)}")
                    _p()
                else:
                    _p(_d("  (no changes)"))
            except Exception as e:
                _p(f"  {_r('✗')} git diff failed: {e}")

        elif cmd == SlashCommand.COPY:
            if self._last_assistant_text:
                try:
                    import pyperclip
                    pyperclip.copy(self._last_assistant_text)
                    _p(f"  {_d('copied to clipboard')}")
                except Exception:
                    _p(f"  {_y('⚠')} could not copy (install pyperclip)")
            else:
                _p(f"  {_d('nothing to copy')}")

        elif cmd == SlashCommand.STATUS:
            sid = self._session.session_id
            _p()
            rows = [
                ("model",    self._config.model),
                ("sandbox",  self._config.sandbox_mode.value),
                ("approval", self._config.ask_for_approval.value),
                ("cwd",      str(Path.cwd())),
                ("session",  sid),
            ]
            for key, val in rows:
                _p(f"  {_d(f'{key:<10}')}  {val}")
            _p()

        elif cmd == SlashCommand.DEBUG_CONFIG:
            import json
            _p(_d(json.dumps(self._config.model_dump(), indent=2, default=str)))

        elif cmd == SlashCommand.MCP:
            from bob.protocol.ops import ListMcpToolsOp
            await self._session.submit(ListMcpToolsOp())
            _p(f"  {_d('listing MCP tools…')}")

        elif cmd == SlashCommand.STOP:
            from bob.protocol.ops import CleanBackgroundTerminalsOp
            await self._session.submit(CleanBackgroundTerminalsOp())
            _p(f"  {_d('stopping background terminals…')}")

        elif cmd == SlashCommand.REVIEW:
            try:
                diff = subprocess.run(
                    ["git", "diff", "HEAD", "--stat"], capture_output=True,
                    text=True, cwd=Path.cwd(), timeout=5,
                ).stdout.strip() or "(no diff)"
                _p(f"  {_d('spawning review agent…')}")
                tm = self._session.ensure_thread_manager()
                agent_id = await tm.spawn(
                    task=(
                        f"Review the following git diff and identify any bugs, "
                        f"security issues, or improvements needed:\n\n{diff}"
                    ),
                    template="verify",
                )
                _p(f"  {_d(f'review agent started (id={agent_id})')}")
            except Exception as exc:
                _p(f"  {_r('✗')} {exc}")

        elif cmd == SlashCommand.RENAME:
            name = args.strip()
            if name:
                from bob.protocol.ops import SetThreadNameOp
                await self._session.submit(SetThreadNameOp(name=name))
                _p(f"  {_d(f'renamed to: {name}')}")
            else:
                _p(f"  {_y('⚠')} usage: /rename <new name>")

        elif cmd == SlashCommand.INIT:
            try:
                from bob.instructions.loader import create_agents_md
                path = create_agents_md(Path.cwd())
                _p(f"  {_d(f'created {path}')}")
            except Exception as e:
                _p(f"  {_r('✗')} {e}")

        elif cmd == SlashCommand.RESUME:
            try:
                sessions = await self._session.list_sessions()
            except Exception:
                sessions = []
            if not sessions:
                _p(f"  {_d('no saved sessions')}")
            else:
                _p()
                for i, s in enumerate(sessions[:10], 1):
                    label = getattr(s, "name", None) or getattr(s, "id", "?")[:12]
                    _p(f"  {_d(str(i) + '.')}  {label}")
                _p()
                try:
                    ps = PromptSession()
                    raw = await ps.prompt_async("  select number or id: ")
                    idx = int(raw.strip()) - 1
                    if 0 <= idx < len(sessions):
                        s = sessions[idx]
                        await self._session.resume(s.path)
                        label = getattr(s, "name", None) or getattr(s, "id", "?")[:12]
                        _p(f"  {_d(f'resumed: {label}')}")
                except Exception:
                    _p(f"  {_d('cancelled')}")

        elif cmd == SlashCommand.DEBUG_M_DROP:
            from bob.protocol.ops import DropMemoriesOp
            await self._session.submit(DropMemoriesOp())
            _p(f"  {_d('dropped all memories')}")

        # ── Phase 1: help, model, effort, cost, usage ─────────────────────────

        elif cmd == SlashCommand.HELP:
            _p()
            groups = [
                ("Navigation",  [SlashCommand.NEW, SlashCommand.RESUME, SlashCommand.FORK,
                                  SlashCommand.REWIND, SlashCommand.CLEAR]),
                ("Session",     [SlashCommand.STATUS, SlashCommand.COST, SlashCommand.USAGE,
                                  SlashCommand.COMPACT, SlashCommand.EXPORT, SlashCommand.COPY,
                                  SlashCommand.RENAME]),
                ("Tools",       [SlashCommand.DIFF, SlashCommand.COMMIT, SlashCommand.BRANCH,
                                  SlashCommand.CONTEXT, SlashCommand.SUMMARY, SlashCommand.REVIEW]),
                ("Config",      [SlashCommand.MODEL, SlashCommand.EFFORT, SlashCommand.OUTPUT_STYLE,
                                  SlashCommand.THEME, SlashCommand.VI, SlashCommand.APPROVALS]),
                ("Agent",       [SlashCommand.PLAN, SlashCommand.AGENT, SlashCommand.SUBAGENTS,
                                  SlashCommand.MCP, SlashCommand.HOOKS]),
                ("System",      [SlashCommand.DOCTOR, SlashCommand.INIT, SlashCommand.FEEDBACK,
                                  SlashCommand.QUIT]),
            ]
            for group, cmds in groups:
                _p(f"  {_b(group)}")
                for c in cmds:
                    desc = COMMAND_DESCRIPTIONS.get(c, "")
                    _p(f"    {_c('/' + c.value):<30}  {_d(desc)}")
                _p()

        elif cmd == SlashCommand.MODEL:
            await self._handle_model_picker(args.strip())

        elif cmd == SlashCommand.EFFORT:
            level = args.strip().lower()
            valid = {"low", "medium", "high"}
            if level not in valid:
                _p(f"  {_y('⚠')} usage: /effort <low|medium|high>")
            else:
                try:
                    from bob.config.schema import ReasoningEffort
                    effort_map = {
                        "low":    ReasoningEffort.LOW,
                        "medium": ReasoningEffort.MEDIUM,
                        "high":   ReasoningEffort.HIGH,
                    }
                    self._config = self._config.model_copy(
                        update={"reasoning_effort": effort_map[level]}
                    )
                    _p(f"  {_d(f'reasoning effort set to: {level}')}")
                except Exception:
                    _p(f"  {_d(f'reasoning effort set to: {level}')}")

        elif cmd == SlashCommand.COST:
            # Rough cost estimate (OpenAI pricing as of 2024, per 1k tokens)
            _RATES: dict[str, tuple[float, float]] = {
                "gpt-4o":           (0.005,  0.015),
                "gpt-4o-mini":      (0.00015, 0.0006),
                "gpt-4-turbo":      (0.01,   0.03),
                "gpt-4":            (0.03,   0.06),
                "gpt-3.5-turbo":    (0.0005, 0.0015),
                "o1":               (0.015,  0.06),
                "o1-mini":          (0.003,  0.012),
                "o3-mini":          (0.0011, 0.0044),
            }
            model_key = self._config.model.lower()
            rate_in, rate_out = 0.0, 0.0
            for k, rates in _RATES.items():
                if k in model_key:
                    rate_in, rate_out = rates
                    break
            cost_in  = self._total_input_tokens  / 1000 * rate_in
            cost_out = self._total_output_tokens / 1000 * rate_out
            # Cached tokens cost ~10% of normal input rate
            cost_cached = self._total_cached_input_tokens / 1000 * rate_in * 0.1
            total_cost = cost_in + cost_out + cost_cached
            savings = self._total_cached_input_tokens / 1000 * rate_in * 0.9
            _p()
            _p(f"  {_d('input tokens')}   {self._total_input_tokens:>10,}   ${cost_in:.4f}")
            _p(f"  {_d('cached tokens')}  {self._total_cached_input_tokens:>10,}   ${cost_cached:.4f}")
            _p(f"  {_d('output tokens')}  {self._total_output_tokens:>10,}   ${cost_out:.4f}")
            _p(f"  {_d('total estimate')} {'':>10}   ${total_cost:.4f}")
            if savings > 0:
                _p(f"  {_g('cache savings')}   {'':>10}   ${savings:.4f}")
            if rate_in == 0:
                _p(f"  {_d('(rates unknown for this model)')}")
            _p()

        elif cmd == SlashCommand.USAGE:
            t = self._last_turn_tokens
            if not t:
                _p(f"  {_d('no turns yet')}")
            else:
                _p()
                _p(f"  {_d('last turn input')}   {t.get('input', 0):>8,}")
                cached = t.get('cached', 0)
                if cached > 0:
                    _p(f"  {_g('last turn cached')}  {cached:>8,}")
                _p(f"  {_d('last turn output')}  {t.get('output', 0):>8,}")
                _p()

        # ── Phase 3: git, export, rewind, summary, doctor, context, style ─────

        elif cmd == SlashCommand.COMMIT:
            try:
                status = subprocess.run(
                    ["git", "status", "--short"], capture_output=True, text=True,
                    cwd=Path.cwd(), timeout=5,
                ).stdout.strip()
                if not status:
                    _p(f"  {_d('nothing to commit')}")
                    return False
                # Auto-stage if nothing is staged
                staged = subprocess.run(
                    ["git", "diff", "--cached", "--name-only"], capture_output=True,
                    text=True, cwd=Path.cwd(), timeout=5,
                ).stdout.strip()
                if not staged:
                    _p(f"  {_d('staging all changes…')}")
                    subprocess.run(["git", "add", "-A"], cwd=Path.cwd(), timeout=5)
                diff = subprocess.run(
                    ["git", "diff", "--cached"], capture_output=True, text=True,
                    cwd=Path.cwd(), timeout=5,
                ).stdout[:8000]
                _p(f"  {_d('generating commit message…')}")
                msg = await self._quick_model_turn(
                    f"Write a concise git commit message (one line) for this diff. "
                    f"Output ONLY the message text, nothing else.\n\n{diff}"
                )
                msg = msg.strip().strip('"').strip("'")
                if msg:
                    result = subprocess.run(
                        ["git", "commit", "-m", msg], capture_output=True, text=True,
                        cwd=Path.cwd(), timeout=10,
                    )
                    if result.returncode == 0:
                        _p(f"  {_g('✓')} committed: {msg[:80]}")
                    else:
                        _p(f"  {_r('✗')} git commit failed: {result.stderr.strip()}")
            except Exception as exc:
                _p(f"  {_r('✗')} {exc}")

        elif cmd == SlashCommand.BRANCH:
            name = args.strip()
            if not name:
                _p(f"  {_y('⚠')} usage: /branch <name>")
            else:
                try:
                    result = subprocess.run(
                        ["git", "checkout", "-b", name], capture_output=True,
                        text=True, cwd=Path.cwd(), timeout=5,
                    )
                    if result.returncode == 0:
                        _p(f"  {_g('✓')} created and checked out branch: {name}")
                    else:
                        _p(f"  {_r('✗')} {result.stderr.strip()}")
                except Exception as exc:
                    _p(f"  {_r('✗')} {exc}")

        elif cmd == SlashCommand.EXPORT:
            import time as _time
            dest = args.strip()
            if not dest:
                ts = int(_time.time())
                dest = str(Path.home() / f"bob-export-{ts}.md")
            try:
                items = self._session.context_manager.raw_items()
                lines = [f"# Bob Session Export\n"]
                for item in items:
                    role = item.get("role", "")
                    content = item.get("content", "")
                    if isinstance(content, list):
                        text = "".join(
                            c.get("text", "") for c in content
                            if isinstance(c, dict) and c.get("type") == "text"
                        )
                    else:
                        text = str(content)
                    if role == "user":
                        lines.append(f"\n## User\n\n{text}\n")
                    elif role == "assistant":
                        lines.append(f"\n## Bob\n\n{text}\n")
                Path(dest).write_text("\n".join(lines), encoding="utf-8")
                _p(f"  {_g('✓')} exported to: {dest}")
            except Exception as exc:
                _p(f"  {_r('✗')} {exc}")

        elif cmd == SlashCommand.REWIND:
            try:
                n = int(args.strip()) if args.strip() else 1
            except ValueError:
                n = 1
            from bob.protocol.ops import UndoOp
            await self._session.submit(UndoOp(turns=n))
            _p(f"  {_d(f'rewound {n} turn(s)')}")

        elif cmd == SlashCommand.SUMMARY:
            _p(f"  {_d('summarizing session…')}")
            await self._quick_model_turn(
                "Summarize what has been accomplished in this session so far. "
                "Be concise — highlight key decisions, files changed, and current state."
            )

        elif cmd == SlashCommand.DOCTOR:
            import shutil as _shutil
            _p()
            checks: list[tuple[bool, str]] = []

            # 1. API key
            api_key = (
                getattr(self._config, "api_key", "") or
                os.environ.get("OPENAI_API_KEY", "") or
                os.environ.get("BOB_API_KEY", "")
            )
            checks.append((bool(api_key), "OPENAI_API_KEY is set"))

            # 2. Git available
            checks.append((bool(_shutil.which("git")), "git is in PATH"))

            # 3. Config valid
            try:
                self._config.model_validate(self._config.model_dump())
                checks.append((True, "config is valid"))
            except Exception as exc:
                checks.append((False, f"config error: {exc}"))

            # 4. httpx available (for web_fetch)
            try:
                import httpx
                checks.append((True, "httpx available (web_fetch)"))
            except ImportError:
                checks.append((False, "httpx not installed (pip install httpx)"))

            # 5. Node.js available (for js_repl)
            checks.append((bool(_shutil.which("node")), "node.js in PATH (js_repl)"))

            for ok, label in checks:
                icon = _g("✓") if ok else _r("✗")

        elif cmd == SlashCommand.TASKS:
            # Display task list
            task_db = getattr(self._session, '_task_db', None)
            if task_db is None:
                _p(f"  {_r('✗')} Task database not available")
            else:
                from bob.core.task_db import TaskStatus
                
                # Parse optional status filter
                status_filter = None
                if args.strip():
                    try:
                        status_filter = TaskStatus(args.strip().lower())
                    except ValueError:
                        _p(f"  {_r('✗')} Invalid status: {args.strip()}")
                        _p(f"  Available: pending, in_progress, completed, cancelled")
                        return False
                
                try:
                    tasks = task_db.list_tasks(status=status_filter)
                    
                    if not tasks:
                        if status_filter:
                            _p(f"  {_d(f'No tasks with status: {status_filter.value}')}")
                        else:
                            _p(f"  {_d('No tasks found')}")
                    else:
                        _p()
                        if status_filter:
                            _p(f"  {_b(f'Tasks ({status_filter.value}):')}")
                        else:
                            _p(f"  {_b('All Tasks:')}")
                        _p()
                        
                        for task in tasks:
                            task_id = task.get('task_id', '?')
                            title = task.get('title', '')
                            status = task.get('status', '?')
                            priority = task.get('priority', '?')
                            
                            # Color-code by status
                            if status == 'completed':
                                status_icon = _g('✓')
                            elif status == 'in_progress':
                                status_icon = _cy('▶')
                            elif status == 'cancelled':
                                status_icon = _r('✗')
                            else:
                                status_icon = _d('○')
                            
                            # Color-code by priority
                            if priority == 'high':
                                priority_text = _r(priority)
                            elif priority == 'medium':
                                priority_text = _y(priority)
                            else:
                                priority_text = _d(priority)
                            
                            _p(f"  {status_icon} [{_cy(task_id)}] {title}")
                            _p(f"    {_d('Status:')} {status} {_d('|')} {_d('Priority:')} {priority_text}")
                        
                        _p()
                        _p(f"  {_d(f'Total: {len(tasks)} task(s)')}")
                except Exception as exc:
                    _p(f"  {_r('✗')} Error listing tasks: {exc}")


                _p(f"  {icon}  {label}")
            _p()

        elif cmd == SlashCommand.CONTEXT:
            arg = args.strip()
            if not arg:
                _p(f"  {_y('⚠')} usage: /context <url|file>")
            else:
                try:
                    if arg.startswith("http://") or arg.startswith("https://"):
                        try:
                            import httpx
                            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as cl:
                                resp = await cl.get(arg, headers={"User-Agent": "bob/1.0"})
                                raw = resp.text
                            try:
                                import html2text
                                h = html2text.HTML2Text()
                                h.ignore_links = False
                                h.body_width = 0
                                raw = h.handle(raw)
                            except ImportError:
                                pass
                            raw = raw[:20000]
                            self._pending_context_items.append(f"[Context from {arg}]\n{raw}")
                            _p(f"  {_g('✓')} added URL context ({len(raw)} chars)")
                        except ImportError:
                            _p(f"  {_r('✗')} httpx not installed")
                    else:
                        p = Path(arg)
                        if not p.is_absolute():
                            p = Path.cwd() / p
                        text = p.read_text(encoding="utf-8", errors="replace")[:20000]
                        self._pending_context_items.append(f"[Context from {p.name}]\n{text}")
                        _p(f"  {_g('✓')} added file context: {p.name} ({len(text)} chars)")
                except Exception as exc:
                    _p(f"  {_r('✗')} {exc}")

        elif cmd == SlashCommand.OUTPUT_STYLE:
            from bob.protocol.config_types import OutputStyle
            
            if not args.strip():
                # Show current style
                current = self._config.output_style.value
                _p(f"  Current output style: {_cy(current)}")
                _p(f"  Available: {_d('brief')}, {_d('normal')}, {_d('verbose')}")
            else:
                style_arg = args.strip().lower()
                try:
                    new_style = OutputStyle(style_arg)
                    self._config.output_style = new_style
                    
                    # Persist to config file
                    await self._save_config()
                    
                    # Reload system prompt for next turn
                    await self._session._load_system_prompt()
                    
                    _p(f"  {_g('✓')} Output style set to: {_cy(new_style.value)}")
                    _p(f"  {_d('Takes effect on next turn')}")
                except ValueError:
                    _p(f"  {_r('✗')} Invalid style: {style_arg}")
                    _p(f"  Available: {_d('brief')}, {_d('normal')}, {_d('verbose')}")

        elif cmd == SlashCommand.BRIEF:
            # Alias for /output-style brief
            from bob.protocol.config_types import OutputStyle
            self._config.output_style = OutputStyle.BRIEF
            await self._save_config()
            await self._session._load_system_prompt()
            _p(f"  {_g('✓')} Output style set to: {_cy('brief')}")
            _p(f"  {_d('Takes effect on next turn')}")

        # ── Phase 5: vi mode, hooks ────────────────────────────────────────────

        elif cmd == SlashCommand.VI:
            self._vi_mode = not self._vi_mode
            self._vi_mode_changed = True
            state = "enabled" if self._vi_mode else "disabled"
            _p(f"  {_d(f'vi mode {state}')}")

        elif cmd == SlashCommand.HOOKS:
            hooks = getattr(self._config, "hooks", [])
            if not hooks:
                _p(f"  {_d('no hooks configured')}")
            else:
                _p()
                for h in hooks:
                    name    = getattr(h, "name",    "?")
                    event   = getattr(h, "event",   "?")
                    command = getattr(h, "command",  "?")
                    timeout = getattr(h, "timeout", "")
                    _p(f"  {_b(name)}  {_d(event)}  {command}" + (f"  {_d(str(timeout)+'ms')}" if timeout else ""))
                _p()

        elif cmd == SlashCommand.THINK:
            try:
                budget = int(args.strip()) if args.strip() else 5000
                if budget < 0:
                    _p(f"  {_y('⚠')} thinking budget must be positive")
                else:
                    self._next_turn_thinking_budget = budget
                    _p(f"  {_d(f'thinking budget set to {budget:,} tokens for next turn')}")
            except ValueError:
                _p(f"  {_y('⚠')} usage: /think [budget_tokens]  (default: 5000)")

        else:
            _p(f"  {_y('⚠')} /{cmd.value} not yet implemented")

        return False

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def _busy_wait(self, ps: PromptSession) -> None:
        """Spin while the model is working.

        Called AFTER input_task is fully cancelled (prompt torn down), so it
        is safe to start the spinner here without overlapping with ❯.
        Handles approval prompts inline.  Ctrl+C sends an InterruptOp.
        """
        await self._start_spinner()
        try:
            while self._task_running or self._pending_approval is not None:
                if self._pending_approval is not None:
                    # Spinner is stopped by the event consumer before printing the
                    # approval header; just handle the prompt here.
                    _, fut = self._pending_approval
                    try:
                        raw = await ps.prompt_async(_APPROVAL_PROMPT)
                    except EOFError:
                        raw = "n"
                    except KeyboardInterrupt:
                        if not fut.done():
                            fut.set_result("n")
                        self._exit_requested.set()
                        return
                    if not fut.done():
                        fut.set_result(raw.strip().lower())
                    # Give the event consumer time to clear pending_approval
                    while self._pending_approval is not None:
                        await asyncio.sleep(0.01)
                    self._approval_event.clear()
                    # Restart spinner if the turn is still running
                    if self._task_running and not self._spinner_active:
                        await self._start_spinner()
                else:
                    try:
                        await asyncio.sleep(0.05)
                    except KeyboardInterrupt:
                        self._exit_requested.set()
                        return
        finally:
            await self._stop_spinner()

    async def _handle_model_picker(self, search: str) -> None:
        """Interactive /model picker — filter by search string, pick by number."""
        from bob.llm.catalog import get_catalog

        catalog = get_catalog()
        current = self._config.model

        # ── No catalog: fall back to direct set or show current ──────────
        if not catalog.is_populated():
            if search and not search.isdigit():
                # Treat as a direct model name — backward-compat
                self._config = self._config.model_copy(update={"model": search})
                self._session.client = self._session._make_client(search)
                _p(f"  {_g('✓')} Model set to: {_b(search)}")
                _p(f"  {_d('(tip: run  python scripts/build_model_catalog.py  for the full picker)')}")
            else:
                _p(f"  current model: {_b(current)}")
                _p(f"  {_d('Model catalog not built — run: python scripts/build_model_catalog.py')}")
                _p(f"  {_d('Usage: /model <name>   e.g.  /model claude-3-5-sonnet-20241022')}")
            return

        # ── Filter models ─────────────────────────────────────────────────
        all_models = catalog.list_models(status="active")
        if search:
            s = search.lower()
            models = [
                m for m in all_models
                if s in m["model_id"].lower()
                or s in (m.get("provider") or "").lower()
                or s in (m.get("family") or "").lower()
                or s in (m.get("display_name") or "").lower()
            ]
        else:
            models = all_models

        if not models:
            _p(f"  {_y('⚠')}  No models found matching {_b(repr(search))}")
            _p(f"  {_d('Try: /model gpt   /model claude   /model gemini   /model llama')}")
            return

        MAX_ROWS = 30
        shown = models[:MAX_ROWS]

        # ── Display table ─────────────────────────────────────────────────
        _p()
        header = f"  {'#':<4} {'Model ID':<44} {'Provider':<12} {'Context':<9} {'$/1M in  out'}"
        _p(_d(header))
        _p(_d("  " + "─" * (len(header) - 2)))

        for i, m in enumerate(shown, 1):
            mid      = m["model_id"]
            provider = m.get("provider") or ""
            ctx      = m.get("context_window")
            ctx_str  = f"{ctx // 1000}K" if ctx else "—"
            inp      = m.get("input_price_per_1m")
            out      = m.get("output_price_per_1m")
            if inp is not None and out is not None:
                price_str = f"${inp:<6.2f}  ${out:.2f}"
            else:
                price_str = "—"
            marker = f" {_g('←')}" if mid == current else ""
            num    = _d(f"{i}.")
            _p(f"  {num:<6} {mid:<44} {_d(provider):<12} {_d(ctx_str):<9} {_d(price_str)}{marker}")

        if len(models) > MAX_ROWS:
            _p(_d(f"\n  … {len(models) - MAX_ROWS} more — narrow your search (e.g. /model gemini-2)"))

        _p()
        _p(_d(f"  current: {current}"))
        _p()

        # ── Prompt for selection ──────────────────────────────────────────
        try:
            ps = PromptSession()
            raw = await ps.prompt_async(
                ANSI(f"  {_c('Enter number or model name')} {_d('(Enter = cancel)')} {_cb('›')} ")
            )
            raw = raw.strip()
        except (KeyboardInterrupt, EOFError):
            _p(_d("  cancelled"))
            return

        if not raw:
            _p(_d("  cancelled"))
            return

        # ── Resolve selection ─────────────────────────────────────────────
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(shown):
                chosen = shown[idx]["model_id"]
            else:
                _p(f"  {_y('⚠')}  Invalid number — must be 1–{len(shown)}")
                return
        else:
            chosen = raw  # direct model name typed by user

        # ── Apply ─────────────────────────────────────────────────────────
        self._config = self._config.model_copy(update={"model": chosen})
        self._session.client = self._session._make_client(chosen)

        # Show what we switched to (with pricing if available)
        info = catalog.get_model(chosen)
        if info:
            ctx   = info.get("context_window")
            inp   = info.get("input_price_per_1m")
            out   = info.get("output_price_per_1m")
            ctx_s = f"  context: {ctx // 1000}K" if ctx else ""
            pr_s  = f"  ${inp:.2f}/${out:.2f} per 1M" if (inp is not None and out is not None) else ""
            _p(f"  {_g('✓')} Model set to: {_b(chosen)}{_d(ctx_s + pr_s)}")
        else:
            _p(f"  {_g('✓')} Model set to: {_b(chosen)}")

    async def run(self) -> None:  # noqa: C901
        completer = _SlashCompleter()
        # Persist history across sessions in ~/.bob/history
        _hist_dir = Path.home() / ".bob"
        _hist_dir.mkdir(parents=True, exist_ok=True)
        _history = FileHistory(str(_hist_dir / "history"))

        def _make_session() -> PromptSession:
            # Custom key bindings for multi-line input
            kb = KeyBindings()
            
            @kb.add(Keys.Enter)
            def _(event):
                """Enter submits the input."""
                event.current_buffer.validate_and_handle()
            
            @kb.add(Keys.Escape, Keys.Enter)  # Alt+Enter for newline (works cross-platform)
            def _(event):
                """Alt+Enter inserts a newline."""
                event.current_buffer.insert_text('\n')
            
            return PromptSession(
                history=_history,
                completer=completer,
                complete_while_typing=True,
                complete_in_thread=True,
                enable_history_search=True,
                vi_mode=self._vi_mode,
                multiline=True,
                key_bindings=kb,
                complete_style='MULTI_COLUMN',
            )

        ps: PromptSession = _make_session()

        self._print_header()   # rich Panel — before patch_stdout

        with patch_stdout():
            event_task = asyncio.create_task(self._consume_events())

            try:
                while True:
                    completer.task_running = self._task_running

                    # Recreate PromptSession if vi mode was toggled
                    if self._vi_mode_changed:
                        self._vi_mode_changed = False
                        ps = _make_session()

                    # ── Wait while busy ───────────────────────────────────────
                    if self._task_running or self._pending_approval is not None:
                        await self._busy_wait(ps)

                    # Clear any stale events left from the busy period
                    self._approval_event.clear()
                    self._turn_started.clear()

                    if self._done.is_set() or self._exit_requested.is_set():
                        break

                    # ── ❯ prompt — interruptible by turn-start or approval ────
                    #
                    # _turn_started fires the moment TurnStartedEvent arrives in
                    # the event consumer, cancelling the ❯ before any stray
                    # prompt character is committed to screen.
                    input_task    = asyncio.ensure_future(
                        ps.prompt_async(self._prompt_str)
                    )
                    wake_tasks = [
                        asyncio.ensure_future(self._turn_started.wait()),
                        asyncio.ensure_future(self._approval_event.wait()),
                    ]

                    done_set, _ = await asyncio.wait(
                        {input_task, *wake_tasks},
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    # Cancel whatever didn't finish
                    for t in wake_tasks:
                        if t not in done_set:
                            t.cancel()
                            try:
                                await t
                            except (asyncio.CancelledError, Exception):
                                pass

                    if input_task not in done_set:
                        # A wake event fired — cancel the prompt and loop back
                        input_task.cancel()
                        try:
                            await input_task
                        except (asyncio.CancelledError, Exception):
                            pass
                        continue   # re-enters _busy_wait at top of loop

                    # ── User submitted text ───────────────────────────────────
                    try:
                        text = input_task.result()
                    except (EOFError, KeyboardInterrupt):
                        _p(f"  {_d('goodbye')}")
                        self._exit_requested.set()
                        break

                    text = text.strip()
                    if not text:
                        continue

                    if text.startswith("/"):
                        cmd, args = parse_command(text)
                        if cmd is None:
                            _p(f"  {_r('✗')} unknown command: {text}")
                            continue
                        if await self._dispatch_slash(cmd, args):
                            break

                    elif text.startswith("!"):
                        shell_cmd = text[1:].strip()
                        if shell_cmd:
                            from bob.protocol.ops import RunUserShellCommandOp
                            await self._session.submit(
                                RunUserShellCommandOp(command=shell_cmd)
                            )

                    else:
                        from bob.protocol.items import TextUserInput
                        from bob.protocol.ops import UserTurnOp
                        # Prepend any pending context items
                        full_text = text
                        if self._pending_context_items:
                            ctx_block = "\n\n".join(self._pending_context_items)
                            full_text = f"{ctx_block}\n\n{text}"
                            self._pending_context_items.clear()
                        # Inject output style directive
                        if self._output_style != "normal":
                            full_text = (
                                f"[Respond in {self._output_style} style]\n{full_text}"
                            )
                        
                        # Detect thinking trigger keywords
                        text_lower = text.lower()
                        thinking_triggers = ["ultrathink", "think hard", "think deeply", "think step by step", "think carefully"]
                        if any(trigger in text_lower for trigger in thinking_triggers):
                            if self._next_turn_thinking_budget is None:
                                self._next_turn_thinking_budget = 10000
                                _p(f"  {_d('💭 extended thinking enabled (10k tokens)')}")
                        
                        # Apply thinking budget if set
                        if self._next_turn_thinking_budget is not None:
                            self._config = self._config.model_copy(
                                update={"thinking_budget_tokens": self._next_turn_thinking_budget}
                            )
                            self._next_turn_thinking_budget = None  # Reset after use
                        
                        self._task_running = True   # optimistic: prevents stray › before TurnStartedEvent
                        await self._session.submit(
                            UserTurnOp(items=[TextUserInput(type="text", text=full_text)])
                        )
                        
                        # Reset thinking budget after turn
                        if self._config.thinking_budget_tokens > 0:
                            self._config = self._config.model_copy(update={"thinking_budget_tokens": 0})

                    if self._done.is_set() or self._exit_requested.is_set():
                        break

            finally:
                event_task.cancel()
                try:
                    await event_task
                except asyncio.CancelledError:
                    pass


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_interface(session, config: BobConfig) -> None:
    """Called from bob/cli/main.py after BobSession is started."""
    await Interface(session=session, config=config).run()
