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
from prompt_toolkit.patch_stdout import patch_stdout

from rich.console import Console

from bob.config.schema import BobConfig
from bob.tui.slash_commands import (
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
_RED = "\033[31m"   # red
_GRN = "\033[32m"   # green
_YLW = "\033[33m"   # yellow
_CYN = "\033[36m"   # cyan


def _d(s: str) -> str:   return f"{_DIM}{s}{_R}"
def _b(s: str) -> str:   return f"{_BLD}{s}{_R}"
def _r(s: str) -> str:   return f"{_RED}{s}{_R}"
def _g(s: str) -> str:   return f"{_GRN}{s}{_R}"
def _y(s: str) -> str:   return f"{_YLW}{s}{_R}"
def _c(s: str) -> str:   return f"{_CYN}{s}{_R}"
def _cb(s: str) -> str:  return f"{_CYN}{_BLD}{s}{_R}"


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
    task_running: bool = False

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        if " " in text:
            return
        query = text[1:]
        for m in fuzzy_match_commands(query, self.task_running):
            val  = m.command.value
            desc = COMMAND_DESCRIPTIONS.get(m.command, "")
            yield Completion(
                val,
                start_position=-len(query),
                display=val,
                display_meta=desc,
            )


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

    # ── Dynamic prompt ────────────────────────────────────────────────────────

    def _prompt_str(self) -> ANSI:
        """❯ — never shown while task is running (main loop guards this)."""
        return ANSI("❯ ")

    # ── Header — Claude Code-style welcome panel ──────────────────────────────

    def _print_header(self) -> None:
        model   = self._config.model
        sandbox = self._config.sandbox_mode.value
        cwd     = Path.cwd()

        # Shorten cwd with ~ like Claude Code does
        home = Path.home()
        try:
            rel = cwd.relative_to(home)
            sep = "\\" if sys.platform == "win32" else "/"
            cwd_str = "~" + sep + str(rel) if str(rel) != "." else "~"
        except ValueError:
            cwd_str = str(cwd)

        # Bob version
        try:
            from importlib.metadata import version as _pkg_ver
            bob_version = _pkg_ver("bob")
        except Exception:
            bob_version = "0.1.0"

        # Terminal width
        term_w = shutil.get_terminal_size((120, 24)).columns

        # Column layout: │ sp [LEFT] sp │ sp [RIGHT] sp │
        #  char count:   1  1   L    1  1  1    R    1  1  = L + R + 7
        LEFT  = 52
        RIGHT = max(20, term_w - LEFT - 7)

        # ANSI helpers (raw — written via sys.__stdout__ before patch_stdout)
        RST   = "\033[0m"
        DIM   = "\033[2m"
        BOLD  = "\033[1m"
        BRAND = "\033[38;2;215;119;87m"  # exact Anthropic brand orange rgb(215,119,87)

        def vlen(s: str) -> int:
            """Visible length — strips ANSI escape codes."""
            return len(re.sub(r"\033\[[0-9;]*m", "", s))

        def center(s: str, w: int = LEFT) -> str:
            """Center an ANSI-aware string in a field of width w."""
            v = vlen(s)
            if v >= w:
                return s
            pl = (w - v) // 2
            pr = w - v - pl
            return " " * pl + s + " " * pr

        def rpad(s: str, w: int) -> str:
            """Right-pad an ANSI-aware string to visible width w."""
            v = vlen(s)
            return s if v >= w else s + " " * (w - v)

        # Mascot (Unicode block chars, Claude Code Clawd-style)
        mascot = [
            f"{BRAND}▐▛███▜▌{RST}",     # 7 visible chars
            f"{BRAND}▝▜█████▛▘{RST}",   # 9 visible chars
            f"{BRAND}  ▘▘ ▝▝  {RST}",   # 9 visible chars
        ]

        # Left column (52 visible chars wide)
        left_rows = [
            " " * LEFT,
            center(f"{BRAND}Welcome to bob!{RST}"),
            " " * LEFT,
            center(mascot[0]),
            center(mascot[1]),
            center(mascot[2]),
            " " * LEFT,
            "  " + rpad(f"{DIM}{model} · {sandbox}{RST}", LEFT - 2),
            "  " + rpad(f"{DIM}{cwd_str}{RST}",           LEFT - 2),
            " " * LEFT,
        ]

        # Right column
        right_rows = [
            f"{BOLD}Tips for getting started{RST}",
            f"{DIM}Run /init to create an AGENTS.md file{RST}",
            f"{DIM}{'─' * min(RIGHT - 2, 55)}{RST}",
            f"{BOLD}Recent activity{RST}",
            f"{DIM}No recent activity{RST}",
            "",
            "",
            "",
            "",
            "",
        ]

        # Pad to equal row count
        n = max(len(left_rows), len(right_rows))
        while len(left_rows)  < n: left_rows.append(" " * LEFT)
        while len(right_rows) < n: right_rows.append("")

        # Build box
        title  = f"bob v{bob_version}"
        ndash  = max(0, term_w - 5 - len(title) - 2)
        top    = f"╭─── {title} {'─' * ndash}╮"
        bot    = "╰" + "─" * (term_w - 2) + "╯"

        out = sys.__stdout__
        out.write("\n" + top + "\n")
        for l, r in zip(left_rows, right_rows):
            out.write(f"│ {rpad(l, LEFT)} │ {rpad(r, RIGHT)} │\n")
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
        label  = _SPINNER_LABEL
        width  = len(label) + 6
        i = 0
        try:
            while not self._spinner_stop.is_set():
                frame = frames[i % len(frames)]
                out.write(f"\r  \033[36m{frame}\033[0m \033[2m{label}\033[0m")
                out.flush()
                i += 1
                await asyncio.sleep(0.08)
        finally:
            out.write("\r" + " " * width + "\r")
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

    def _print_tool_output(self, lines: list[str]) -> None:
        """⎿ on first output line, indent on rest, dim for collapsed-count sentinel."""
        for i, line in enumerate(lines):
            if line.startswith("\x00DIM"):        # collapsed count sentinel
                _p(f"     {_d(line[4:])}")
                continue
            prefix = "  ⎿ " if i == 0 else "     "
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
            SessionEndedEvent,
            TextDeltaEvent,
            TurnEndedEvent,
            TurnInterruptedEvent,
            TurnStartedEvent,
            WarningEvent,
        )

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
                        _p(f"\033[38;2;215;119;87m•\033[0m ", end="")
                    _p(msg.delta, end="")
                    self._current_buf += msg.delta

                # ── Command execution ─────────────────────────────────────────

                elif isinstance(msg, ExecStartedEvent):
                    await self._stop_spinner()
                    if self._current_buf and not self._current_buf.endswith("\n"):
                        _p()
                    self._current_buf     = ""
                    self._exec_output_buf = []
                    if msg.tool_call_id not in self._approved_ids:
                        tool_label, cmd_arg = self._format_command(msg.command)
                        # blank line before tool header only when following prose
                        if not self._after_tool:
                            _p()
                        self._print_tool_header(tool_label, cmd_arg)
                        self._after_tool = False
                    else:
                        self._approved_ids.discard(msg.tool_call_id)

                elif isinstance(msg, ExecOutputEvent):
                    self._exec_output_buf.extend(msg.data.splitlines())

                elif isinstance(msg, ExecCompletedEvent):
                    self._print_tool_output(_collapse_lines(self._exec_output_buf))
                    self._exec_output_buf = []
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
                    if self._current_buf and not self._current_buf.endswith("\n"):
                        _p()
                    elif self._after_tool and not self._current_buf:
                        # Turn ended with only tool calls and no prose — add spacing
                        _p()
                    self._last_assistant_text = self._current_buf
                    self._current_buf  = ""
                    self._after_tool   = False
                    self._task_running = False
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

                elif isinstance(msg, SessionEndedEvent):
                    self._done.set()
                    return

            except Exception:
                pass

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
                    ["git", "diff", "--stat", "HEAD"],
                    capture_output=True, text=True, cwd=Path.cwd(), timeout=5,
                )
                out = result.stdout or result.stderr or "(no changes)"
                _p(_d(out.rstrip()))
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

    async def run(self) -> None:  # noqa: C901
        completer = _SlashCompleter()
        # Persist history across sessions in ~/.bob/history
        _hist_dir = Path.home() / ".bob"
        _hist_dir.mkdir(parents=True, exist_ok=True)
        _history = FileHistory(str(_hist_dir / "history"))
        ps: PromptSession = PromptSession(
            history=_history,
            completer=completer,
            complete_while_typing=True,
            enable_history_search=True,
        )

        self._print_header()   # rich Panel — before patch_stdout

        with patch_stdout():
            event_task = asyncio.create_task(self._consume_events())

            try:
                while True:
                    completer.task_running = self._task_running

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
                        self._task_running = True   # optimistic: prevents stray › before TurnStartedEvent
                        await self._session.submit(
                            UserTurnOp(items=[TextUserInput(type="text", text=text)])
                        )

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
