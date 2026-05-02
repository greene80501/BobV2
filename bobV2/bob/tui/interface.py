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
import datetime as _dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.application.current import get_app
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.patch_stdout import patch_stdout

from rich.console import Console

from bob.config.schema import BobConfig
from bob.tui.markdown_engine import MarkdownRenderStyle, StreamState, create_markdown_engine
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

_R   = "\033[0m"                     # reset
_DIM = "\033[2m"                     # dim
_BLD = "\033[1m"                     # bold
_RED = "\033[38;2;255;85;85m"        # red
_GRN = "\033[38;2;80;200;120m"       # green
_YLW = "\033[38;2;255;195;0m"        # yellow
_CYN = "\033[38;2;0;200;220m"        # cyan
_PRP = "\033[38;2;164;110;255m"      # purple (#a46eff)
_BLU = "\033[38;2;21;98;254m"        # blue  (#1562fe)
_BRD = "\033[38;2;88;99;122m"        # slate border
_SFT = "\033[38;2;148;163;184m"      # soft text


def _d(s: str) -> str:   return f"{_DIM}{s}{_R}"
def _b(s: str) -> str:   return f"{_BLD}{s}{_R}"
def _r(s: str) -> str:   return f"{_RED}{s}{_R}"
def _g(s: str) -> str:   return f"{_GRN}{s}{_R}"
def _y(s: str) -> str:   return f"{_YLW}{s}{_R}"
def _c(s: str) -> str:   return f"{_PRP}{s}{_R}"
def _cy(s: str) -> str:  return _c(s)
def _cb(s: str) -> str:  return f"{_BLU}{_BLD}{s}{_R}"
def _cg(s: str) -> str:  return f"{_GRN}{s}{_R}"
def _bd(s: str) -> str:  return f"{_BRD}{s}{_R}"
def _s(s: str) -> str:   return f"{_SFT}{s}{_R}"
def _bold(s: str) -> str: return f"{_BLD}{s}{_R}"


# ── Markdown renderer ────────────────────────────────────────────────────────

_UND  = "\033[4m"   # underline
_STR  = "\033[9m"   # strikethrough
_CODE_FG = "\033[96m"          # bright-cyan text for inline code
_H1_FG   = "\033[97m"          # bright white
_H2_FG   = "\033[97m"          # bright white
_H3_FG   = "\033[36m"          # cyan
_LINK_FG = _BLU


def _print_stream_code_block(text: str) -> None:
    for line in text.rstrip("\n").splitlines() or [""]:
        if line:
            _p(f"{_CODE_FG}{line}{_R}")
        else:
            _p("")


def _truncate_cmd(s: str, max_len: int = 120) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[:max_len - 1] + "…"


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
_UI_LOG_SINK = None


def _visible_len(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def _pad_visible(text: str, width: int) -> str:
    return text + (" " * max(0, width - _visible_len(text)))


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _p(s: str = "", end: str = "\n") -> None:
    """Print ANSI text via prompt_toolkit — safe inside patch_stdout on all platforms."""
    print_formatted_text(ANSI(s + end), end="")
    if _UI_LOG_SINK is not None:
        try:
            _UI_LOG_SINK(_strip_ansi(s + end))
        except Exception:
            pass


# ── Thinking-trail helpers ────────────────────────────────────────────────────

_TOOL_VERBS: dict[str, str] = {
    "read_file":      "read",
    "write_file":     "wrote",
    "edit_file":      "edited",
    "shell":          "ran",
    "web_search":     "searched",
    "web_fetch":      "fetched",
    "glob_files":     "globbed",
    "apply_patch":    "patched",
    "notebook_read":  "read nb",
    "notebook_edit":  "edited nb",
    "view_image":     "viewed",
    "browser":        "browser",
}


def _format_tool_key_arg(tool_name: str, tool_input: dict) -> str:
    """Return the most human-readable single argument for a tool call."""
    from pathlib import Path as _P
    if tool_name in ("read_file", "write_file", "edit_file", "view_image"):
        p = tool_input.get("path", "")
        return _P(p).name if p else ""
    if tool_name == "list_dir":
        p = tool_input.get("path", "")
        return str(p)[:60] if p else "."
    if tool_name == "shell":
        cmd = tool_input.get("command", "")
        if isinstance(cmd, list):
            cmd = " ".join(cmd)
        return _truncate_cmd(str(cmd), 60)
    if tool_name == "web_search":
        return str(tool_input.get("query", ""))[:60]
    if tool_name == "web_fetch":
        return str(tool_input.get("url", ""))[:60]
    if tool_name == "glob_files":
        return str(tool_input.get("pattern", ""))[:60]
    if tool_name in ("apply_patch",):
        patch = tool_input.get("patch", "") or tool_input.get("content", "")
        for line in str(patch).splitlines():
            for prefix in ("*** Add File: ", "*** Update File: ", "*** Delete File: "):
                if line.startswith(prefix):
                    return line[len(prefix):].strip()
    if tool_name == "browser":
        action = tool_input.get("action", "")
        if action == "navigate":
            url = tool_input.get("url", "")
            try:
                from urllib.parse import urlparse as _up
                p = _up(url)
                short = p.netloc + (p.path[:25] if len(p.path) > 1 else "")
                return f"navigate → {short}"
            except Exception:
                return f"navigate → {url[:40]}"
        if action == "scroll":
            x, y = tool_input.get("x", 0), tool_input.get("y", 0)
            parts = []
            if x:
                parts.append(f"x={x}")
            if y:
                parts.append(f"y={y}")
            return ("scroll  " + ", ".join(parts)) if parts else "scroll"
        if action == "click":
            return f"click  {tool_input.get('selector', '')[:35]}"
        if action == "form_input":
            return f"type → {tool_input.get('selector', '')[:30]}"
        if action == "find_elements":
            return f"find  {tool_input.get('selector', '')[:35]}"
        if action == "execute_js":
            return "execute js"
        if action == "type_text":
            text = tool_input.get("text", "")
            preview = text[:40].replace("\n", "↵")
            return f"type  \"{preview}{'…' if len(text) > 40 else ''}\""
        return action.replace("_", " ")
    return ""


def _print_activity_line(
    tool_name: str,
    tool_input: dict,
    duration_ms: int,
    *,
    error: str | None = None,
) -> None:
    """Print a single-line activity record for a completed tool call."""
    icon = _r("✗") if error else _g("✓")
    verb = _TOOL_VERBS.get(tool_name, tool_name.replace("_", " "))
    key_arg = _format_tool_key_arg(tool_name, tool_input or {})
    dur_str = f"  {_d(f'{duration_ms}ms')}" if duration_ms else ""
    arg_str = f"  {_s(key_arg)}" if key_arg else ""
    _p(f"  {icon} {_d(verb)}{arg_str}{dur_str}")


def _print_thinking_summary(token_count: int, tool_log: list) -> None:
    """Print a single collapsed activity line at end of turn.

    Groups repeated tool calls and sums their durations.
    Only shown when at least one tool was called.
    """
    if not tool_log:
        return
    groups: dict = {}
    order: list[str] = []
    for entry in tool_log:
        name = entry[0]
        duration_ms = entry[2] if len(entry) > 2 else 0
        error = entry[3] if len(entry) > 3 else None
        if name not in groups:
            groups[name] = {"count": 0, "total_ms": 0, "errors": 0}
            order.append(name)
        groups[name]["count"] += 1
        groups[name]["total_ms"] += duration_ms or 0
        if error:
            groups[name]["errors"] += 1
    has_errors = any(g["errors"] for g in groups.values())
    icon = _r("✗") if has_errors else _g("✓")
    parts: list[str] = []
    for name in order:
        g = groups[name]
        verb = _TOOL_VERBS.get(name, name.replace("_", " "))
        count_str = f" ×{g['count']}" if g["count"] > 1 else ""
        total_ms = g["total_ms"]
        if total_ms >= 1000:
            dur_str = f"  {_d(f'{total_ms / 1000:.1f}s')}"
        elif total_ms > 0:
            dur_str = f"  {_d(f'{total_ms}ms')}"
        else:
            dur_str = ""
        err_count = g["errors"]
        err_str = f" {_r(f'({err_count} err)')}" if err_count else ""
        parts.append(f"{_d(verb + count_str)}{dur_str}{err_str}")
    if parts:
        sep = f"  {_d('·')}  "
        _p(f"  {icon}  {sep.join(parts)}")


def _render_error(message: str, tool_name: str | None = None, tool_input: dict | None = None) -> None:
    """Print an error with file:line highlighting and optional traceback rendering."""
    import re as _re
    import io as _io
    import json as _json

    prefix = f"  {_r('✗')}"
    if tool_name:
        prefix += f" {_d(f'[{tool_name}]')}"
    if tool_input is not None:
        try:
            rendered_input = _json.dumps(tool_input, ensure_ascii=True, default=str)
        except Exception:
            rendered_input = str(tool_input)
        if len(rendered_input) > 200:
            rendered_input = rendered_input[:200] + "..."
        prefix += f" {_d(f'input={rendered_input}')}"

    # Detect Python traceback: starts with "Traceback (most recent call last):"
    is_traceback = "Traceback (most recent call last)" in message
    # Detect file:line patterns
    has_file_ref = bool(_re.search(
        r'(?:[/\\][\w./-]+|[\w.-]+)\.(py|ts|js|jsx|tsx|rs|go|java|cpp|c|h):(\d+)',
        message
    ))

    if is_traceback:
        # Use Rich to render a highlighted traceback
        try:
            from rich.console import Console
            from rich.panel import Panel
            import shutil as _sh
            sio = _io.StringIO()
            console = Console(file=sio, force_terminal=True,
                              width=_sh.get_terminal_size((120, 24)).columns - 4)
            console.print(Panel(
                message, title="[red]Error[/red]",
                border_style="red", padding=(0, 1)
            ))
            for line in sio.getvalue().splitlines():
                _p(f"  {line}")
            return
        except Exception:
            pass  # fall through to plain rendering

    if has_file_ref:
        # Highlight file:line references inline
        def _hl(m):
            path, ext, lineno = m.group(1), m.group(2), m.group(3)
            return f"\033[36m{path}.{ext}\033[0m:{_y(lineno)}"
        highlighted = _re.sub(
            r'((?:[/\\][\w./-]+|[\w.-]+)\.(py|ts|js|jsx|tsx|rs|go|java|cpp|c|h)):(\d+)',
            _hl,
            message,
        )
        _p(f"{prefix} {highlighted}")
    else:
        _p(f"{prefix} {message}")


# ── Approval prompt string (shared between event consumer and main loop) ───────

_APPROVAL_PROMPT = ANSI(
    f"  {_d('[y]')} yes  "
    f"{_d('[a]')} always  "
    f"{_d('[n]')} no  "
    f"{_d('[s]')} skip  "
    f"› "
)


_IMAGE_EXTS = frozenset([".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg"])


def _parse_at_images(text: str) -> tuple[str, list]:
    """Extract @path/to/image.ext tokens from *text*.

    Returns (cleaned_text, [Path, ...]) where image paths have been removed
    from the text and collected separately.
    """
    import re
    from pathlib import Path as _P
    image_paths: list = []
    # Match @<non-whitespace> tokens
    pattern = re.compile(r"@(\S+)")

    def _replace(m):
        raw = m.group(1).rstrip(".,;:!?")  # strip trailing punctuation
        p = _P(raw)
        if p.suffix.lower() in _IMAGE_EXTS:
            if p.exists():
                image_paths.append(p.resolve())
                return ""  # remove from text
        return m.group(0)  # leave non-image @mentions unchanged

    cleaned = pattern.sub(_replace, text).strip()
    return cleaned, image_paths


class _AsciiArtPreParser(HTMLParser):
    """Extract per-character foreground colors from the uploaded HTML art."""

    def __init__(self) -> None:
        super().__init__()
        self._in_pre = False
        self._current_fg: tuple[int, int, int] | None = None
        self._current_bg: tuple[int, int, int] | None = None
        self.lines: list[
            list[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None]]
        ] = [[]]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "pre":
            self._in_pre = True
            return
        if not self._in_pre or tag != "span":
            return
        style = attr_map.get("style") or ""
        fg = re.search(r"(?:^|;)\s*color:\s*rgb\((\d+),(\d+),(\d+)\)", style)
        bg = re.search(r"(?:^|;)\s*background-color:\s*rgb\((\d+),(\d+),(\d+)\)", style)
        self._current_fg = tuple(int(part) for part in fg.groups()) if fg else None
        self._current_bg = tuple(int(part) for part in bg.groups()) if bg else None

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            self._in_pre = False
        elif self._in_pre and tag == "span":
            self._current_fg = None
            self._current_bg = None

    def handle_data(self, data: str) -> None:
        if not self._in_pre:
            return
        text = html.unescape(data).replace("\xa0", " ")
        for ch in text:
            if ch == "\n":
                self.lines.append([])
            else:
                self.lines[-1].append((ch, self._current_fg, self._current_bg))


def _256_to_rgb(n: int) -> tuple[int, int, int]:
    """Convert a 256-color palette index to an approximate (r, g, b) triple."""
    if n < 16:
        _std = [
            (0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0),
            (0, 0, 128), (128, 0, 128), (0, 128, 128), (192, 192, 192),
            (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0),
            (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
        ]
        return _std[n]
    if n < 232:
        n -= 16
        return (int((n // 36) * 51), int(((n % 36) // 6) * 51), int((n % 6) * 51))
    v = (n - 232) * 10 + 8
    return (v, v, v)


def _parse_ansi_text_art(
    source: str,
) -> tuple[
    tuple[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None], ...],
    ...,
]:
    """Parse ANSI-decorated text art into the common cell grid representation.

    Handles both 24-bit true-color (38;2;r;g;b) and 256-color palette (38;5;n)
    escape sequences so that art files using either encoding render correctly.
    """
    ansi_re = re.compile(r"\033\[([0-9;]*)m")
    rows: list[
        tuple[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None], ...]
    ] = []

    for raw_line in source.strip("\n").replace("\ufeff", "").replace("\\e", "\033").splitlines():
        fg: tuple[int, int, int] | None = None
        bg: tuple[int, int, int] | None = None
        row: list[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None]] = []
        index = 0
        while index < len(raw_line):
            match = ansi_re.match(raw_line, index)
            if match:
                params = [int(part) for part in match.group(1).split(";") if part] if match.group(1) else [0]
                cursor = 0
                while cursor < len(params):
                    code = params[cursor]
                    if code == 0:
                        fg = None
                        bg = None
                    elif code == 39:
                        fg = None
                    elif code == 49:
                        bg = None
                    # 24-bit true color: 38;2;r;g;b
                    elif code == 38 and cursor + 4 < len(params) and params[cursor + 1] == 2:
                        fg = (params[cursor + 2], params[cursor + 3], params[cursor + 4])
                        cursor += 4
                    elif code == 48 and cursor + 4 < len(params) and params[cursor + 1] == 2:
                        bg = (params[cursor + 2], params[cursor + 3], params[cursor + 4])
                        cursor += 4
                    # 256-color palette: 38;5;n
                    elif code == 38 and cursor + 2 < len(params) and params[cursor + 1] == 5:
                        fg = _256_to_rgb(params[cursor + 2])
                        cursor += 2
                    elif code == 48 and cursor + 2 < len(params) and params[cursor + 1] == 5:
                        bg = _256_to_rgb(params[cursor + 2])
                        cursor += 2
                    cursor += 1
                index = match.end()
                continue
            row.append((raw_line[index], fg, bg))
            index += 1
        rows.append(tuple(row))

    width = max((len(row) for row in rows), default=0)
    return tuple(
        tuple(list(row) + [(" ", None, None)] * (width - len(row)))
        for row in rows
    )


def _unwrap_shell_printf_art(source: str) -> str:
    """Extract the quoted payload from a shell `printf "..."` art file.

    Handles files that begin with a shebang (#!/usr/bin/env sh) by stripping
    any leading comment/shebang lines before searching for the printf call.
    """
    stripped = source.replace("\ufeff", "").strip()
    # Drop shebang / comment lines so the regex can anchor to printf
    if stripped.startswith("#"):
        lines = stripped.splitlines()
        stripped = "\n".join(
            ln for ln in lines if not ln.startswith("#")
        ).strip()
    match = re.match(
        r'^\s*printf\s+(?P<quote>["\'])(?P<body>.*)(?P=quote)\s*;?\s*$',
        stripped,
        re.DOTALL,
    )
    if not match:
        return stripped
    return match.group("body")


@lru_cache(maxsize=1)
def _load_tui_bob_art() -> tuple[
    tuple[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None], ...],
    ...,
]:
    """Load Bob's embedded ANSI art from the repository asset file."""
    art_dir = Path(__file__).resolve().parents[3] / "chacter"
    for name in ("bob_tui_ansi.sh", "bob_tui_ansi.txt", "bob_tui_ansi.ans", "img.ANS"):
        art_path = art_dir / name
        if not art_path.exists():
            continue
        raw_source = art_path.read_text(encoding="utf-8")
        normalized = _unwrap_shell_printf_art(raw_source)
        art = _parse_ansi_text_art(normalized)
        if art:
            return art
    return tuple()


@lru_cache(maxsize=1)
def _load_uploaded_ascii_art() -> tuple[
    tuple[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None], ...],
    ...,
]:
    """Load the newest generated or uploaded colored ASCII art from the repo."""
    art_dir = Path(__file__).resolve().parents[3] / "chacter"
    candidates = sorted(art_dir.glob("bob-terminal-*.html"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        candidates = sorted(art_dir.glob("ascii-art-*.html"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        return tuple()
    art_path = candidates[-1]

    parser = _AsciiArtPreParser()
    parser.feed(art_path.read_text(encoding="utf-8"))
    lines = parser.lines
    if lines and not lines[-1]:
        lines.pop()
    if not lines:
        return tuple()

    width = max(len(line) for line in lines)
    normalized: list[
        tuple[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None], ...]
    ] = []
    for line in lines:
        padded = list(line)
        if len(padded) < width:
            padded.extend([(" ", None, None)] * (width - len(padded)))
        normalized.append(tuple(padded))
    return tuple(normalized)


def _crop_ascii_art(
    art: tuple[
        tuple[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None], ...],
        ...,
    ],
) -> tuple[
    tuple[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None], ...],
    ...,
]:
    """Trim fully empty rows and columns from the uploaded art."""
    if not art:
        return art

    height = len(art)
    width = len(art[0])

    visible_rows = [
        i for i, row in enumerate(art)
        if any(ch != " " or bg is not None for ch, _, bg in row)
    ]
    visible_cols = [
        j for j in range(width)
        if any(art[i][j][0] != " " or art[i][j][2] is not None for i in range(height))
    ]

    if not visible_rows or not visible_cols:
        return art

    top = visible_rows[0]
    bottom = visible_rows[-1]
    left = visible_cols[0]
    right = visible_cols[-1]

    return tuple(
        tuple(row[left:right + 1])
        for row in art[top:bottom + 1]
    )


def _scale_ascii_art(
    art: tuple[
        tuple[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None], ...],
        ...,
    ],
    target_width: int,
) -> tuple[
    tuple[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None], ...],
    ...,
]:
    """Scale the uploaded art proportionally using nearest-neighbor sampling."""
    if not art:
        return art

    src_h = len(art)
    src_w = len(art[0])
    if target_width >= src_w or target_width <= 0:
        return art

    scale = target_width / src_w
    target_h = max(1, round(src_h * scale))
    scaled: list[
        tuple[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None], ...]
    ] = []
    for y in range(target_h):
        src_y = min(src_h - 1, int((y + 0.5) / scale))
        row: list[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None]] = []
        for x in range(target_width):
            src_x = min(src_w - 1, int((x + 0.5) / scale))
            row.append(art[src_y][src_x])
        scaled.append(tuple(row))
    return tuple(scaled)


def _fit_ascii_art(
    art: tuple[
        tuple[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None], ...],
        ...,
    ],
    *,
    max_width: int,
    max_height: int,
) -> tuple[
    tuple[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None], ...],
    ...,
]:
    """Downscale art proportionally so it fits the available width and height."""
    if not art or max_width <= 0 or max_height <= 0:
        return tuple()

    src_h = len(art)
    src_w = len(art[0])
    if src_w <= max_width and src_h <= max_height:
        return art

    scale = min(max_width / src_w, max_height / src_h)
    if scale >= 1:
        return art

    target_w = max(1, min(max_width, int(src_w * scale)))
    scaled = _scale_ascii_art(art, target_w)
    if len(scaled) > max_height:
        trimmed = list(scaled[:max_height])
        return tuple(trimmed)
    return scaled


def _render_ascii_art_lines(
    art: tuple[
        tuple[tuple[str, tuple[int, int, int] | None, tuple[int, int, int] | None], ...],
        ...,
    ],
    *,
    color: bool,
) -> list[str]:
    """Render the uploaded art grid as ANSI terminal lines."""
    if not art:
        return []
    if not color:
        return ["".join(ch for ch, _, _ in row) for row in art]

    reset = "\033[0m"
    lines: list[str] = []

    for row in art:
        parts: list[str] = []
        current_style: tuple[
            tuple[int, int, int] | None,
            tuple[int, int, int] | None,
        ] | None = None
        for ch, fg, bg in row:
            fg = _remap_ascii_art_color(fg)
            bg = _remap_ascii_art_color(bg)
            style = (fg, bg)
            if style != current_style:
                if fg is None and bg is None:
                    parts.append(reset)
                else:
                    # Always emit BOTH fg and bg so neither bleeds from the
                    # previous cell — this eliminates the gray-stripe artifact.
                    codes: list[str] = []
                    if fg is not None:
                        codes.append(f"38;2;{fg[0]};{fg[1]};{fg[2]}")
                    else:
                        codes.append("39")   # default foreground
                    if bg is not None:
                        codes.append(f"48;2;{bg[0]};{bg[1]};{bg[2]}")
                    else:
                        codes.append("49")   # default background
                    parts.append(f"\033[{';'.join(codes)}m")
                current_style = style
            parts.append(ch)
        parts.append(reset)
        lines.append("".join(parts))

    return lines


def _remap_ascii_art_color(
    color: tuple[int, int, int] | None,
) -> tuple[int, int, int] | None:
    """Preserve source colors for generated art."""
    return color


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
        
        # Handle @filename autocomplete
        if "@" in text:
            at_pos = text.rfind("@")
            if at_pos >= 0:
                prefix = text[at_pos+1:]
                yield from self._complete_filename(prefix)
                return
        
        # Handle #tool autocomplete
        if "#" in text:
            hash_pos = text.rfind("#")
            if hash_pos >= 0:
                prefix = text[hash_pos+1:]
                yield from self._complete_tool(prefix)
                return
        
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
            from bob.llm.compatibility import get_picker_seed_models, get_model_compatibility

            catalog = get_catalog()
            merged: dict[str, dict] = {
                row["model_id"]: dict(row) for row in get_picker_seed_models()
            }
            if catalog.is_populated():
                catalog_models = catalog.search_models(query) if query else catalog.list_models(status="active")
                for row in catalog_models:
                    compat = get_model_compatibility(row["model_id"], catalog_provider=row.get("provider"))
                    merged[row["model_id"]] = {
                        **merged.get(row["model_id"], {}),
                        **row,
                        "route": compat.route.value,
                        "support_level": compat.support_level.value,
                    }
            models = list(merged.values())
            if query:
                q = query.lower()
                models = [
                    row for row in models
                    if q in str(row.get("model_id", "")).lower()
                    or q in str(row.get("provider", "")).lower()
                    or q in str(row.get("family", "")).lower()
                    or q in str(row.get("display_name", "")).lower()
                ]
            for m in models[:40]:
                mid      = m["model_id"]
                provider = m.get("provider") or ""
                ctx      = m.get("context_window")
                ctx_str  = f"{ctx // 1000}K" if ctx else ""
                inp      = m.get("input_price_per_1m")
                price    = f"${inp:.2f}/1M" if inp is not None else ""
                support  = m.get("support_level") or ""
                meta     = "  ".join(x for x in [provider, ctx_str, price, support] if x)
                yield Completion(
                    mid,
                    start_position=-len(query),
                    display=mid,
                    display_meta=meta,
                )
        except Exception:
            pass


class _ModelPickerCompleter(Completer):
    """Searchable completion menu for the interactive /model picker."""

    def __init__(self, models: list[dict], current_model: str):
        self._models = models
        self._current_model = current_model

    def get_completions(self, document, complete_event):
        query = document.text_before_cursor.strip().lower()
        start_position = -len(document.text_before_cursor)

        for model in self._filter_models(query):
            model_id = model["model_id"]
            provider = model.get("provider") or ""
            family = model.get("family") or ""
            ctx = model.get("context_window")
            ctx_str = f"{ctx // 1000}K" if ctx else ""
            inp = model.get("input_price_per_1m")
            out = model.get("output_price_per_1m")
            support = model.get("support_level") or ""
            route = model.get("route") or ""
            price = (
                f"${inp:.2f}/${out:.2f}"
                if inp is not None and out is not None
                else ""
            )
            current = "current" if model_id == self._current_model else ""
            meta = "  ".join(
                part for part in (provider, family, support, route, ctx_str, price, current) if part
            )
            display = f"{model_id}  *" if model_id == self._current_model else model_id
            yield Completion(
                model_id,
                start_position=start_position,
                display=display,
                display_meta=meta,
            )

    def _filter_models(self, query: str) -> list[dict]:
        if not query:
            return self._models

        matches: list[tuple[int, str, dict]] = []
        for model in self._models:
            haystacks = [
                model.get("model_id", ""),
                model.get("provider", ""),
                model.get("family", ""),
                model.get("display_name", ""),
            ]
            score = 99
            matched = False
            for field in haystacks:
                text = str(field or "").lower()
                idx = text.find(query)
                if idx != -1:
                    matched = True
                    score = min(score, idx)
            if matched:
                matches.append((score, model.get("model_id", ""), model))

        matches.sort(key=lambda row: (row[0], row[1]))
        return [row[2] for row in matches]
    
    def _complete_filename(self, prefix: str):
        """Yield filename completions for @filename syntax."""
        from pathlib import Path
        import os
        
        try:
            # Get current working directory
            cwd = Path.cwd()
            
            # If prefix contains path separator, split into dir and file parts
            if "/" in prefix or "\\" in prefix:
                path_obj = Path(prefix)
                search_dir = cwd / path_obj.parent if not path_obj.is_absolute() else path_obj.parent
                file_prefix = path_obj.name
            else:
                search_dir = cwd
                file_prefix = prefix
            
            if not search_dir.exists():
                return
            
            # List files and directories matching prefix
            for item in sorted(search_dir.iterdir()):
                name = item.name
                if name.startswith(file_prefix) or not file_prefix:
                    # Skip hidden files unless prefix starts with .
                    if name.startswith(".") and not file_prefix.startswith("."):
                        continue
                    
                    display_name = name + ("/" if item.is_dir() else "")
                    rel_path = str(item.relative_to(cwd)) if item.is_relative_to(cwd) else str(item)
                    from pathlib import Path as _P
                    ext = _P(name).suffix.lower()
                    if item.is_dir():
                        meta = "dir"
                    elif ext in _IMAGE_EXTS:
                        meta = "image"
                    else:
                        meta = "file"
                    yield Completion(
                        rel_path,
                        start_position=-len(prefix),
                        display=display_name,
                        display_meta=meta,
                    )
        except Exception:
            pass
    
    def _complete_tool(self, prefix: str):
        """Yield tool name completions for #tool syntax."""
        try:
            # Get available tools from session
            from bob.tools.registry import get_tool_registry
            registry = get_tool_registry()
            
            tool_names = registry.list_tool_names()
            
            for tool_name in sorted(tool_names):
                if tool_name.startswith(prefix) or not prefix:
                    # Get tool description if available
                    try:
                        tool = registry.get_tool(tool_name)
                        desc = getattr(tool, 'description', '') or ''
                        # Truncate long descriptions
                        if len(desc) > 60:
                            desc = desc[:57] + "..."
                    except Exception:
                        desc = ""
                    
                    yield Completion(
                        tool_name,
                        start_position=-len(prefix),
                        display=tool_name,
                        display_meta=desc
                    )
        except Exception:
            # Fallback to common tool names if registry not available
            common_tools = [
                "read_file", "write_to_file", "list_files", "search_files",
                "execute_command", "apply_diff", "web_search", "web_fetch"
            ]
            for tool_name in common_tools:
                if tool_name.startswith(prefix) or not prefix:
                    yield Completion(
                        tool_name,
                        start_position=-len(prefix),
                        display=tool_name
                    )


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
        self._reasoning_peek: str = ""
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
        # Per-turn activity tracking for thinking trail
        self._turn_tool_log: list[tuple[str, dict, int]] = []  # (name, input, duration_ms)
        self._reasoning_token_count: int = 0
        # Code block tracking for syntax highlighting
        self._in_code_block = False
        self._code_block_lang: Optional[str] = None
        self._code_block_content = ""
        # Word-wrap buffer for streaming text
        self._wrap_buffer = ""
        self._wrap_column = 0
        # Frame-rate limiting: batch text deltas arriving within 16ms (≈60 fps)
        self._markdown = create_markdown_engine(
            config.markdown_engine,
            MarkdownRenderStyle(
                reset=_R,
                dim=_DIM,
                bold=_BLD,
                underline=_UND,
                strike=_STR,
                border=_BRD,
                soft=_SFT,
                code=_CODE_FG,
                link=_LINK_FG,
                emphasis=_SFT,
                strong=_BLD,
                heading1=_H1_FG,
                heading2=_H2_FG,
                heading3=_H3_FG,
            ),
        )
        self._markdown_stream = StreamState()
        self._stream_last_flush: float = 0.0
        self._tool_call_inputs: dict[str, dict] = {}
        # Approval-in-progress flag (keyboard reader must pause during approval prompts)
        self._approval_active: bool = False
        self._last_spinner_snapshot: str = ""
        self._last_terminal_mutation: str = ""
        # Sub-agent tracking for spinner timers and inspector
        self._active_agents: dict[str, dict] = {}  # agent_id → {name, started_at, last_activity}
        self._task_running_for_agents: bool = False
        self._session_log_path = self._make_session_log_path()
        self._session_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._session_log_handle = self._session_log_path.open("a", encoding="utf-8-sig", buffering=1)
        self._log_ui_line(f"[session] log started for session={getattr(self._session, 'session_id', 'unknown')}")

    def _make_session_log_path(self) -> Path:
        logs_dir = self._session.bob_home / "logs" / "tui"
        session_id = getattr(self._session, "session_id", "session")
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        return logs_dir / f"{stamp}-{session_id}.log"

    def _log_ui_line(self, text: str) -> None:
        cleaned = str(text).replace("\r", "")
        if not cleaned:
            return
        if not cleaned.endswith("\n"):
            cleaned += "\n"
        self._session_log_handle.write(cleaned)
        self._session_log_handle.flush()

    def _log_spinner_snapshot(self, spinner_label: str, agent_lines: list[str]) -> None:
        snapshot = "\n".join([_strip_ansi(f"SPINNER {spinner_label}"), *(_strip_ansi(line) for line in agent_lines)])
        if snapshot != self._last_spinner_snapshot:
            self._last_spinner_snapshot = snapshot
            self._log_ui_line(snapshot)

    def _log_terminal_mutation(self, action: str, *, dedupe: bool = False, **details: object) -> None:
        suffix = ""
        if details:
            parts = [f"{key}={value}" for key, value in details.items()]
            suffix = " " + " ".join(parts)
        line = f"[terminal] {action}{suffix}"
        if dedupe and line == self._last_terminal_mutation:
            return
        self._last_terminal_mutation = line
        self._log_ui_line(line)

    def _log_terminal_block(self, label: str, lines: list[str]) -> None:
        if not lines:
            return
        text = "\n".join(_strip_ansi(line) for line in lines)
        self._log_ui_line(f"[terminal-block] {label}\n{text}")

    def _log_event_message(self, msg: object) -> None:
        event_type = getattr(msg, "type", msg.__class__.__name__)
        try:
            payload = msg.model_dump() if hasattr(msg, "model_dump") else str(msg)
        except Exception:
            payload = str(msg)
        try:
            text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            text = str(payload)
        if len(text) > 4000:
            text = text[:4000] + "... [truncated]"
        self._log_ui_line(f"[event] type={event_type} payload={text}")

    def _log_event_handler_error(self, msg: object, exc: Exception) -> None:
        event_type = getattr(msg, "type", msg.__class__.__name__)
        self._log_ui_line(
            f"[event-error] type={event_type} error={exc.__class__.__name__}: {exc}"
        )

    # ── Dynamic prompt & footer toolbar ──────────────────────────────────────

    def _prompt_str(self) -> ANSI:
        """Left edge of the bordered input box."""
        BLUE = "\033[38;2;21;98;254m"
        RST  = "\033[0m"
        return ANSI(f"│ {BLUE}❯{RST} ")

    def _input_rprompt(self) -> ANSI:
        """Right-side hint shown on the input line."""
        return ANSI("\033[2m→ Enter to send\033[0m │ ")

    @staticmethod
    def _input_box_dash_width(term_width: int | None = None) -> int:
        """Return the dash width used by the bordered prompt box."""
        width = term_width
        if width is None:
            width = shutil.get_terminal_size((120, 24)).columns
        return max(40, width) - 3

    def _print_input_box_top(self) -> None:
        """Print the top border of the input box (into scrollback)."""
        DIM    = "\033[2m"
        RST    = "\033[0m"
        box_w  = self._input_box_dash_width()
        _p(f"{DIM}╭{'─' * box_w}╮{RST}")

    def _footer_toolbar(self) -> ANSI:
        """Bottom border of the input box, shown as bottom toolbar while typing."""
        term_w = max(40, shutil.get_terminal_size((120, 24)).columns)
        DIM    = "\033[2m"
        RST    = "\033[0m"
        box_w  = self._input_box_dash_width(term_w)
        in_t   = self._total_input_tokens
        out_t  = self._total_output_tokens
        counts = f" in: {in_t:,}  out: {out_t:,} "
        dash_w = max(0, box_w - len(counts))
        bottom = "╰" + "─" * dash_w + counts + "╯"
        return ANSI(f"{DIM}{bottom}{RST}")

    def _print_input_box_bottom(self) -> None:
        """Print the bottom border of the input box (into scrollback)."""
        DIM    = "\033[2m"
        RST    = "\033[0m"
        box_w  = self._input_box_dash_width()
        bottom = "╰" + "─" * box_w + "╯"
        _p(f"{DIM}{bottom}{RST}")

    async def _prompt_with_box(self, ps: "PromptSession") -> "str | None":
        """
        Render a 3-line bordered input box using a custom Application so the
        top border, input line, and bottom border all appear together with no
        gap.  Returns submitted text, or None if a wake event cancelled it.
        Raises KeyboardInterrupt / EOFError on exit request.
        """
        from prompt_toolkit.application import Application
        from prompt_toolkit.application import Application
        from prompt_toolkit.layout import Layout, HSplit, VSplit, FloatContainer, Float, Window
        from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
        from prompt_toolkit.layout.dimension import Dimension
        from prompt_toolkit.layout.menus import CompletionsMenu
        from prompt_toolkit.key_binding import merge_key_bindings
        from prompt_toolkit.key_binding.bindings.emacs import load_emacs_bindings
        from prompt_toolkit.key_binding.bindings.vi import load_vi_bindings

        term_w = max(40, shutil.get_terminal_size((120, 24)).columns)
        box_w  = self._input_box_dash_width(term_w)
        row_w = box_w + 2
        DIM, BLUE, RST = "\033[2m", "\033[38;2;21;98;254m", "\033[0m"

        buf = ps.default_buffer
        buf.reset(append_to_history=False)

        submitted: list[str] = []
        cancelled = False

        kb = KeyBindings()

        def _insert_newline(event) -> None:
            event.current_buffer.insert_text('\n')

        @kb.add(Keys.Enter)
        def _enter(event):
            event.current_buffer.validate_and_handle()

        @kb.add(Keys.Escape, Keys.Enter)
        def _alt_enter(event):
            _insert_newline(event)

        @kb.add(Keys.Escape, Keys.ControlM)
        def _alt_enter_ctrl_m(event):
            _insert_newline(event)

        @kb.add(Keys.Escape, Keys.ControlJ)
        def _alt_enter_ctrl_j(event):
            _insert_newline(event)

        @kb.add('/')
        def _slash(event):
            b = event.current_buffer
            b.insert_text("/")
            if b.text == "/" and b.cursor_position == 1:
                b.start_completion(select_first=False)

        @kb.add('c-c')
        def _ctrl_c(event):
            event.app.exit(exception=KeyboardInterrupt())

        @kb.add('c-d')
        def _ctrl_d(event):
            if not event.current_buffer.text:
                event.app.exit(exception=EOFError())

        def _top():
            return ANSI(f"{_BRD}╭{'─' * box_w}╮{RST}")

        def _bottom():
            return ANSI(f"{_BRD}╰{'─' * box_w}╯{RST}")

        def _status():
            in_t  = self._total_input_tokens
            out_t = self._total_output_tokens
            model = self._config.model
            hint = "Enter to send · Alt+Enter newline · / commands · @ files"
            meta = f"{model} · in {in_t:,} · out {out_t:,}"
            pad = max(2, term_w - len(hint) - len(meta) - 2)
            return ANSI(f"{_SFT}{hint}{' ' * pad}{RST}{DIM}{meta}{RST}")

        def _submitted_line(text: str, is_first: bool = False) -> str:
            inner_w = max(1, box_w - 4)
            clipped = text[:inner_w]
            prefix = f"{_bd('│')} {_cb('❯')}  " if is_first else f"{_bd('│')}    "
            content = f"{prefix}{clipped}"
            return f"{_pad_visible(content, box_w + 1)}{_bd('│')}"

        def _line_prefix(lineno, wrap_count):
            if lineno == 0 and wrap_count == 0:
                return ANSI(f"{_BRD}│{RST} {BLUE}❯{RST}  ")
            return ANSI(f"{_BRD}│{RST}    ")

        input_ctrl = BufferControl(
            buffer=buf,
            focusable=True,
            include_default_input_processors=True,
        )

        layout = Layout(
            FloatContainer(
                content=HSplit([
                    Window(
                        height=1,
                        width=Dimension.exact(row_w),
                        dont_extend_width=True,
                        content=FormattedTextControl(_top),
                    ),
                    VSplit([
                        Window(
                            content=input_ctrl,
                            wrap_lines=True,
                            width=Dimension.exact(row_w - 1),
                            height=Dimension(min=1, max=8),
                            dont_extend_height=True,
                            get_line_prefix=_line_prefix,
                        ),
                        Window(
                            width=1,
                            char='│',
                            style='fg:#58637a',
                        ),
                    ], width=Dimension.exact(row_w)),
                    Window(
                        height=1,
                        width=Dimension.exact(row_w),
                        dont_extend_width=True,
                        content=FormattedTextControl(_bottom),
                    ),
                    Window(height=1),
                    Window(height=1, content=FormattedTextControl(_status)),
                ]),
                floats=[Float(xcursor=True, ycursor=True,
                              content=CompletionsMenu(max_height=12, scroll_offset=1))],
            ),
            focused_element=buf,
        )

        base_kb = load_vi_bindings() if self._vi_mode else load_emacs_bindings()
        app: Application = Application(
            layout=layout,
            key_bindings=merge_key_bindings([base_kb, kb]),
            full_screen=False,
            erase_when_done=True,
            mouse_support=False,
        )

        def _accept(b):
            submitted.append(b.text)
            app.exit()

        buf.accept_handler = _accept

        def _refresh_slash(_b):
            if buf.text.startswith("/") and " " not in buf.text:
                buf.start_completion(select_first=False)

        buf.on_text_changed += _refresh_slash

        async def _wake_watcher():
            nonlocal cancelled
            await asyncio.wait(
                {
                    asyncio.ensure_future(self._turn_started.wait()),
                    asyncio.ensure_future(self._approval_event.wait()),
                },
                return_when=asyncio.FIRST_COMPLETED,
            )
            cancelled = True
            app.exit()

        wake_task = asyncio.ensure_future(_wake_watcher())

        try:
            await app.run_async()
        except (KeyboardInterrupt, EOFError):
            if not wake_task.done():
                wake_task.cancel()
                try:
                    await wake_task
                except (asyncio.CancelledError, Exception):
                    pass
            buf.accept_handler = None
            buf.on_text_changed -= _refresh_slash
            raise
        finally:
            if not wake_task.done():
                wake_task.cancel()
                try:
                    await wake_task
                except (asyncio.CancelledError, Exception):
                    pass
            buf.accept_handler = None
            buf.on_text_changed -= _refresh_slash

        # After the app erases itself, immediately re-print the box with the
        # submitted text so it stays visible in the scrollback history.
        if not cancelled and submitted:
            _p(f"{_BRD}╭{'─' * box_w}╮{RST}")
            inner_w = max(1, box_w - 4)
            is_first = True
            for raw_line in submitted[0].splitlines() or [""]:
                remaining = raw_line or ""
                if not remaining:
                    _p(_submitted_line("", is_first=is_first))
                    is_first = False
                    continue
                while remaining:
                    _p(_submitted_line(remaining[:inner_w], is_first=is_first))
                    remaining = remaining[inner_w:]
                    is_first = False
            _p(f"{_BRD}╰{'─' * box_w}╯{RST}")
            _p(f"{_DIM}  …{_R}", end="")  # placeholder — spinner overwrites on first frame

        return None if cancelled else (submitted[0] if submitted else None)

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

    def _recent_session_rows(self, dim: str, bold: str, rst: str) -> list[str]:
        """Return recent session lines for the welcome header."""
        rows = [f"  {bold}Recent Activity{rst}"]
        sessions = self._load_recent_sessions(limit=3)
        if not sessions:
            rows.append(f"  {dim}No recent sessions yet{rst}")
            return rows

        for session in sessions:
            session_id = session["id"][:8]
            name = session["name"]
            when = self._format_header_timestamp(session["updated_at"])
            if len(name) > 25:
                name = name[:22] + "..."
            rows.append(f"  {dim}• {session_id} - {name} ({when}){rst}")
        return rows

    def _load_recent_sessions(self, limit: int = 3) -> list[dict[str, str]]:
        """Load recent sessions from the persisted session index."""
        import sqlite3

        db_path = self._session.bob_home / "state.sqlite"
        if not db_path.exists():
            return []

        current_session_id = getattr(self._session, "session_id", "")
        recent: list[dict[str, str]] = []

        try:
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """
                    SELECT id, name, cwd, updated_at
                    FROM threads
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit + 6,),
                )
                for row in cursor.fetchall():
                    session_id = row["id"] or ""
                    if not session_id or session_id == current_session_id:
                        continue

                    cwd = row["cwd"] or ""
                    label = (row["name"] or "").strip()
                    if not label:
                        label = Path(cwd).name if cwd else "Untitled"

                    recent.append(
                        {
                            "id": session_id,
                            "name": label,
                            "updated_at": row["updated_at"] or "",
                        }
                    )
                    if len(recent) >= limit:
                        break
        except Exception:
            return []

        return recent

    @staticmethod
    def _format_header_timestamp(raw: str) -> str:
        """Format ISO timestamps compactly for the startup header."""
        if not raw:
            return "unknown"

        from datetime import datetime

        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.strftime("%b %d, %H:%M")
        except Exception:
            return raw[:16]

    def _build_header_character(self, max_width: int, max_height: int) -> tuple[list[str], str]:
        """Render Bob's ANSI art, fitting it to the available header space."""
        rst = "\033[0m"
        brand = "" if self._config.no_color else "\033[1;38;5;75m"
        welcome = f"{brand}Welcome to bob!{rst}" if brand else "Welcome to bob!"

        art = _load_tui_bob_art() or _load_uploaded_ascii_art()
        if not art:
            return [], welcome

        cropped = _crop_ascii_art(art)
        scaled = _fit_ascii_art(cropped, max_width=max_width, max_height=max_height)
        lines = _render_ascii_art_lines(scaled, color=not self._config.no_color)
        return lines, welcome

    # ── Header ────────────────────────────────────────────────────────────────

    def _print_header(self) -> None:
        """Print the welcome header directly to sys.__stdout__ before patch_stdout."""
        from bob import __version__

        # ── Color shorthands ──────────────────────────────────────────────
        RST       = "\033[0m"
        DIM       = "\033[2m"
        BOLD      = "\033[1m"
        CYAN_BOLD = "\033[1;38;2;0;200;220m"
        GREEN     = "\033[38;2;80;200;120m"
        YELLOW    = "\033[38;2;255;195;0m"

        def vlen(s: str) -> int:
            return len(re.sub(r"\033\[[0-9;]*m", "", s))

        def pad_r(s: str, w: int) -> str:
            """Right-pad *s* to *w* visible columns."""
            v = vlen(s)
            return s + " " * max(0, w - v)

        def center_in(s: str, w: int) -> str:
            """Center *s* within *w* visible columns."""
            v = vlen(s)
            if v >= w:
                return s
            pl = (w - v) // 2
            return " " * pl + s + " " * (w - v - pl)

        term_w = max(100, shutil.get_terminal_size((120, 24)).columns)
        inner_w = term_w - 2  # space between │ … │

        # ── Metadata ──────────────────────────────────────────────────────
        model   = self._config.model or "unknown"
        cwd_str = str(self._config.exec_cwd or os.getcwd())
        try:
            home = str(Path.home())
            if cwd_str.startswith(home):
                cwd_str = "~" + cwd_str[len(home):]
        except Exception:
            pass
        exec_cwd = str(self._config.exec_cwd or Path.cwd())

        # ── Recent git commits ────────────────────────────────────────────
        recent_commits: list[tuple[str, str, str]] = []
        try:
            r = subprocess.run(
                ["git", "log", "--oneline", "--format=%h|%ar|%s", "-3"],
                capture_output=True, text=True, cwd=exec_cwd, timeout=2,
            )
            if r.returncode == 0:
                for line in r.stdout.strip().splitlines():
                    parts = line.split("|", 2)
                    if len(parts) == 3:
                        recent_commits.append((parts[0], parts[1], parts[2]))
        except Exception:
            pass

        # ── Load and fit Bob art ──────────────────────────────────────────
        art = _load_tui_bob_art() or _load_uploaded_ascii_art()
        cropped = _crop_ascii_art(art) if art else tuple()

        # ── Column geometry ───────────────────────────────────────────────
        left_w   = 40
        right_w  = 34
        sep      = " │ "          # visible separator between columns
        sep_vis  = 3              # visual width of sep
        center_w = max(20, inner_w - left_w - right_w - 2 * sep_vis)

        # Fit art into the centre column
        art_lines: list[str] = []
        if cropped:
            fitted    = _fit_ascii_art(cropped, max_width=center_w, max_height=18)
            art_lines = _render_ascii_art_lines(fitted, color=not self._config.no_color)

        # ── LEFT column ───────────────────────────────────────────────────
        disp_cwd = cwd_str
        max_path = left_w - 15
        if len(disp_cwd) > max_path:
            disp_cwd = "..." + disp_cwd[-(max_path - 3):]

        left: list[str] = [
            f" {CYAN_BOLD}System Info{RST}",
            f"  {BOLD}bob{RST} v{__version__}",
            f"  {DIM}Model:{RST} {model}",
            f"  {DIM}Workspace:{RST} {disp_cwd}",
            f"  {DIM}System:{RST} Bob V2",
            f"  {DIM}Directory:{RST} {disp_cwd}",
            "",
            f" {CYAN_BOLD}Recent Sessions{RST}",
        ]
        for h, t, msg in recent_commits:
            prefix_len = len(h) + len(t) + 4  # "  {h} {t} "
            max_msg = left_w - prefix_len - 1
            if max_msg < 5:
                max_msg = 10
            trunc = (msg[:max_msg - 3] + "...") if len(msg) > max_msg else msg
            left.append(f"  {YELLOW}{h}{RST} {DIM}{t}{RST} {trunc}")

        # ── CENTER column ─────────────────────────────────────────────────
        center: list[str] = [
            center_in(f"\033[1;38;2;80;80;255mWelcome to IBM Bob!{RST}", center_w),
            "",
        ]
        for al in art_lines:
            center.append(center_in(al, center_w))
        center.append("")
        center.append(center_in(f"\033[1;38;2;140;80;255mYour AI coding assistant{RST}", center_w))

        # ── RIGHT column ──────────────────────────────────────────────────
        quick_cmds = [
            ("/help",    "View all commands"),
            ("/new",     "Start new session"),
            ("/resume",  "Continue last session"),
            ("/model",   "Switch AI model"),
            ("/compact", "Compress context"),
            ("/cost",    "View costs"),
            ("/diff",    "Review pending changes"),
            ("/status",  "Review Status"),
            ("/quit",    "Exit bob"),
        ]
        right: list[str] = [f"{CYAN_BOLD}Quick Commands{RST}"]
        for cmd, desc in quick_cmds:
            right.append(f" {GREEN}{cmd:<10}{RST}{DIM}{desc}{RST}")

        # ── Equalise row counts ───────────────────────────────────────────
        n = max(len(left), len(center), len(right))
        left   += [""] * (n - len(left))
        center += [""] * (n - len(center))
        right  += [""] * (n - len(right))

        out = sys.__stdout__

        # ── Top border ────────────────────────────────────────────────────
        rendered_lines = [f"┌{'─' * inner_w}┐"]
        out.write(rendered_lines[0] + "\n")

        # ── Content rows ──────────────────────────────────────────────────
        for i in range(n):
            lc = pad_r(left[i],   left_w)
            cc = pad_r(center[i], center_w)
            rc = pad_r(right[i],  right_w)
            row = f"│{lc}{sep}{cc}{sep}{rc}│"
            rendered_lines.append(row)
            out.write(row + "\n")

        # ── Bottom border ─────────────────────────────────────────────────
        rendered_lines.append(f"└{'─' * inner_w}┘")
        out.write(rendered_lines[-1] + "\n")

        out.flush()
        self._log_terminal_block("header", rendered_lines)

    # ── Spinner ───────────────────────────────────────────────────────────────

    async def _start_spinner(self) -> None:
        self._spinner_stop   = asyncio.Event()
        self._spinner_active = True
        self._spinner_task   = asyncio.create_task(self._run_spinner())
        self._log_terminal_mutation("spinner_started", label=_strip_ansi(self._spinner_label))

    async def _stop_spinner(self) -> None:
        if not self._spinner_active:
            return
        self._spinner_active = False
        self._log_terminal_mutation("spinner_stop_requested", label=_strip_ansi(self._spinner_label))
        if self._spinner_stop:
            self._spinner_stop.set()
        if self._spinner_task and not self._spinner_task.done():
            try:
                await asyncio.wait_for(self._spinner_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                self._spinner_task.cancel()
        self._spinner_task = None

    # ── Agent inspector helpers ───────────────────────────────────────────────

    def _compute_spinner_label(self) -> str:
        if not self._active_agents:
            return self._spinner_label
        now = time.time()
        parts = []
        for info in self._active_agents.values():
            elapsed = int(now - info["started_at"])
            timer = f"{elapsed // 60}:{elapsed % 60:02d}"
            parts.append(f"[{info['name']}] {timer}")
        n = len(parts)
        if n == 1:
            return f"agent: {parts[0]}"
        return f"{n} agents: {' · '.join(parts)}"

    def _draw_inspector_panel(self, selected: int) -> int:
        """Draw agent inspector panel to stdout. Returns number of lines written."""
        agent_ctrl = getattr(self._session, "agent_control", None)
        if not agent_ctrl:
            return 0
        records = [r for r in agent_ctrl.registry._agents.values() if not r.status.is_terminal]
        if not records:
            return 0
        selected = min(selected, len(records) - 1)
        now = time.time()
        out = sys.__stdout__
        lines = 0
        out.write(f"\r  {_DIM}── agents {'─' * 40}{_R}\n")
        lines += 1
        for i, rec in enumerate(records):
            cursor = "▶" if i == selected else " "
            info = self._active_agents.get(rec.agent_id, {})
            t0 = info.get("started_at", now)
            elapsed = int(now - t0)
            timer = f"{elapsed // 60}:{elapsed % 60:02d}"
            activity = rec.progress.last_activity[:42] if rec.progress.last_activity else "starting…"
            out.write(f"  {cursor} {_BLD}[{rec.path.name}]{_R} {_DIM}{timer}{_R}  {activity}\n")
            lines += 1
        out.write(f"  {_DIM}↑↓ navigate · Enter inspect · Esc close{_R}\n")
        lines += 1
        out.flush()
        return lines

    def _clear_inspector_panel(self, lines: int) -> None:
        """Erase the inspector panel by moving cursor up and clearing to end of screen."""
        if lines <= 0:
            return
        out = sys.__stdout__
        out.write(f"\033[{lines}A\033[J")
        out.flush()

    def _print_agent_detail(self, selected: int) -> None:
        """Print detailed status of the selected agent directly to stdout."""
        agent_ctrl = getattr(self._session, "agent_control", None)
        if not agent_ctrl:
            return
        records = [r for r in agent_ctrl.registry._agents.values() if not r.status.is_terminal]
        if not records or selected >= len(records):
            return
        rec = records[selected]
        info = self._active_agents.get(rec.agent_id, {})
        t0 = info.get("started_at", time.time())
        elapsed = int(time.time() - t0)
        timer = f"{elapsed // 60}:{elapsed % 60:02d}"
        out = sys.__stdout__
        out.write(f"\r  {_BLD}── {rec.path.name} {_R}{_DIM}{'─' * 36}{_R}\n")
        out.write(f"  {_DIM}{rec.status.value} · {rec.progress.tool_use_count} tools · {rec.progress.token_count:,} tok · {timer}{_R}\n")
        if rec.progress.recent_activities:
            out.write(f"  {_DIM}recent activity:{_R}\n")
            for act in rec.progress.recent_activities[-5:]:
                out.write(f"    {_DIM}·{_R} {act}\n")
        if rec.task:
            out.write(f"  {_DIM}task:{_R} {rec.task[:120]}\n")
        out.write("\n")
        out.flush()

    # ── Tool-call block helpers ───────────────────────────────────────────────

    async def _run_spinner(self) -> None:
        """Animate the spinner via sys.__stdout__."""
        import time as _time

        out = sys.__stdout__
        frames = _SPINNER_FRAMES
        i = 0

        try:
            while not self._spinner_stop.is_set():
                frame = frames[i % len(frames)]
                spinner_label = self._compute_spinner_label()
                line = f"\r\033[2K  {frame} {_DIM}{spinner_label}{_R}"
                if self._reasoning_peek:
                    line += f"  {_DIM}\"{self._reasoning_peek}\"{_R}"
                out.write(line)

                self._log_spinner_snapshot(spinner_label, [])
                self._log_terminal_mutation(
                    "frame_drawn",
                    dedupe=True,
                    spinner=_strip_ansi(spinner_label),
                    panel_lines=0,
                )

                out.flush()
                i += 1
                await asyncio.sleep(0.08)
        finally:
            self._log_terminal_mutation("clear_spinner_frame", lines=1)
            out.write("\r\033[2K")
            out.write("\r")
            out.flush()

    @staticmethod
    def _format_command(command: list[str]) -> tuple[str, str]:
        """
        Return (tool_label, arg_string) for display.

        Rules:
        - apply_patch  → ("Patch", "file1, file2") extracted from patch text
        - cmd.exe /C … → ("Cmd", inner command)
        - powershell … → ("PowerShell", inner command with wrapper flags stripped)
        - everything else → ("Shell", joined command, truncated to 120 chars)
        """
        if not command:
            return "Shell", ""

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
            return "Cmd", _truncate_cmd(inner)

        # PowerShell wrappers: strip wrapper flags, but keep flags belonging to the inner command.
        if "powershell" in cmd0 or cmd0 in ("pwsh", "pwsh.exe"):
            parts = command[1:]
            while parts and parts[0].startswith("-"):
                flag = parts.pop(0)
                if flag.lower() in ("-command", "-c"):
                    break
            inner = " ".join(parts).strip() or " ".join(command[1:])
            return "PowerShell", _truncate_cmd(inner)

        # Everything else
        return "Shell", _truncate_cmd(" ".join(command))

    def _status_icon(self, status: str) -> str:
        status_norm = (status or "").strip().lower()
        if status_norm == "completed":
            return _g("✓")
        if status_norm == "in_progress":
            return _cy("▶")
        if status_norm == "cancelled":
            return _r("✗")
        if status_norm == "stalled":
            return _y("⏳")
        return _d("○")

    def _status_label(self, status: str) -> str:
        status_norm = (status or "").strip().lower()
        if status_norm in {"pending", "in_progress", "completed", "cancelled", "stalled"}:
            return status_norm
        return "pending"

    def _print_tool_header(self, tool: str, arg: str, suffix: str = "") -> None:
        """Print a compact framed header for a tool block."""
        _p()
        _p(f"  {_bd('╭─')} {_b(tool)}")
        details = arg.strip()
        if suffix:
            details = f"{details}  {suffix}".strip()
        if details:
            _p(f"  {_bd('│')} {_s(details)}")

    def _print_approval_bar(self, label: str, arg: str) -> None:
        """Print a framed approval card."""
        _p()
        _p(f"  {_bd('╭─')} {_y('Approval Required')}")
        _p(f"  {_bd('│')} {_b(label)}")
        if arg:
            _p(f"  {_bd('│')} {_s(arg)}")
        _p(f"  {_bd('╰─')} {_d('confirm to continue')}")

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
        """Print tool output inside a single framed block."""
        if not lines:
            _p(f"  {_bd('│')} {_d('(no output)')}")
            return
        for i, line in enumerate(lines):
            if line.startswith("\x00DIM"):        # collapsed count sentinel
                _p(f"  {_bd('│')} {_d(line[4:])}")
                continue
            if colorize_diff:
                line = self._colorize_diff_line(line)
            _p(f"  {_bd('│')} {line}")

    def _print_tool_footer(self, *, exit_code: int, duration_ms: int) -> None:
        status = _g("done") if exit_code == 0 else _r(f"exit {exit_code}")
        _p(f"  {_bd('╰─')} {status}{_d(f'  ·  {duration_ms}ms')}")

    # ── Event consumer ────────────────────────────────────────────────────────

    def _wrap_streaming_text(self, delta: str) -> str:
        """Word-wrap streaming text to terminal width.
        
        Maintains state across deltas to handle word boundaries correctly.
        Returns the wrapped text ready for printing.
        """
        import shutil
        
        term_width = shutil.get_terminal_size((120, 24)).columns
        # Leave margin for "• " prefix and some padding
        wrap_width = term_width - 4
        
        result = []
        self._wrap_buffer += delta
        
        # Process complete words
        while True:
            # Check if we have a complete word (space or newline)
            space_idx = self._wrap_buffer.find(' ')
            newline_idx = self._wrap_buffer.find('\n')
            
            # Find the nearest delimiter
            if space_idx == -1 and newline_idx == -1:
                # No complete word yet, keep buffering
                break
            
            if newline_idx != -1 and (space_idx == -1 or newline_idx < space_idx):
                # Newline comes first
                word = self._wrap_buffer[:newline_idx]
                self._wrap_buffer = self._wrap_buffer[newline_idx + 1:]
                
                if self._wrap_column + len(word) > wrap_width:
                    result.append('\n')
                    self._wrap_column = 0
                
                result.append(word)
                result.append('\n')
                self._wrap_column = 0
            else:
                # Space comes first
                word = self._wrap_buffer[:space_idx + 1]  # Include the space
                self._wrap_buffer = self._wrap_buffer[space_idx + 1:]
                
                if self._wrap_column + len(word) > wrap_width:
                    result.append('\n')
                    self._wrap_column = 0
                
                result.append(word)
                self._wrap_column += len(word)
        
        return ''.join(result)

    def _flush_wrap_buffer(self) -> str:
        """Flush any partial word buffered by _wrap_streaming_text()."""
        tail = self._wrap_buffer
        self._wrap_buffer = ""
        if tail:
            self._wrap_column += len(tail)
        return tail

    def _flush_completed_stream_lines(self) -> None:
        """Render only completed markdown lines; keep the partial tail buffered."""
        chunk = self._markdown.render_stream_chunk("", self._markdown_stream)
        if chunk.rendered:
            _p(chunk.rendered, end="")



    async def _consume_events(self) -> None:  # noqa: C901
        from bob.protocol.events import (
            AgentSpawnedEvent,
            AgentProgressEvent,
            AgentCompletedEvent,
            BackgroundTerminalOutputEvent,
            HistoryCompactedEvent,
            ErrorEvent,
            ExecApprovalRequestedEvent,
            ExecCompletedEvent,
            ExecOutputEvent,
            ExecStartedEvent,
            InfoEvent,
            McpStartupStatusEvent,
            McpServersRefreshedEvent,
            McpToolsListedEvent,
            NetworkApprovalRequestedEvent,
            PatchApprovalRequestedEvent,
            PlanApprovalRequestedEvent,
            PlanApprovedEvent,
            PlanRejectedEvent,
            ReasoningDeltaEvent,
            SessionEndedEvent,
            SkillsListedEvent,
            TextDeltaEvent,
            ToolCallStartedEvent,
            ToolCallCompletedEvent,
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
                self._log_event_message(msg)
                # ── Turn lifecycle ────────────────────────────────────────────

                if isinstance(msg, TurnStartedEvent):
                    self._task_running = True
                    self._turn_started.set()   # unblocks ❯ prompt immediately
                    self._current_buf  = ""
                    self._text_started = False
                    self._after_tool   = False
                    self._markdown_stream.pending = ""
                    self._wrap_buffer = ""
                    self._wrap_column = 0
                    # Reset per-turn activity tracking
                    self._turn_tool_log = []
                    self._reasoning_token_count = 0
                    self._reasoning_peek = ""
                    # Spinner is started by _busy_wait AFTER the ❯ prompt is
                    # fully torn down — do NOT start it here.

                # ── Streaming text ────────────────────────────────────────────

                elif isinstance(msg, TextDeltaEvent):
                    if not self._text_started:
                        await self._stop_spinner()
                        self._reasoning_peek = ""
                        self._text_started = True
                        # blank line separating tool output from AI prose
                        if self._after_tool:
                            _p()
                        self._after_tool = False
                    
                    # Handle code block syntax highlighting
                    delta = msg.delta
                    self._current_buf += delta
                    
                    # Word-wrap streaming text (skip if in code block)
                    if not self._in_code_block:
                        delta = self._wrap_streaming_text(delta)
                    
                    # Check for code block markers
                    if "```" in delta:
                        lines = delta.split("\n")
                        for line in lines:
                            if line.strip().startswith("```"):
                                if not self._in_code_block:
                                    # Starting a code block
                                    self._in_code_block = True
                                    # Extract language (e.g., ```python)
                                    lang = line.strip()[3:].strip()
                                    self._code_block_lang = lang if lang else "text"
                                    self._code_block_content = ""
                                    _p(f"  {_d(line)}")
                                else:
                                    # Ending a code block - render in a single color
                                    self._in_code_block = False
                                    if self._code_block_content:
                                        _print_stream_code_block(self._code_block_content)

                                    _p(f"  {_d(line)}")
                                    self._code_block_content = ""
                                    self._code_block_lang = None
                            elif self._in_code_block:
                                # Accumulate code block content
                                self._code_block_content += line + "\n"
                            else:
                                # Regular text outside code blocks — buffered
                                self._markdown_stream.pending += line
                    elif self._in_code_block:
                        # Inside code block, accumulate
                        self._code_block_content += delta
                    else:
                        # Regular streaming text — buffered for frame-rate limiting
                        self._markdown_stream.pending += delta

                    # Flush buffer if ≥16ms have elapsed since last render (≈60fps)
                    import time as _time
                    _now = _time.monotonic()
                    if (
                        self._markdown_stream.pending
                        and "\n" in self._markdown_stream.pending
                        and (_now - self._stream_last_flush) >= 0.016
                    ):
                        self._flush_completed_stream_lines()
                        self._stream_last_flush = _now
                        await asyncio.sleep(0)  # yield to event loop between batches

                # ── Tool call lifecycle ───────────────────────────────────────

                elif isinstance(msg, ToolCallStartedEvent):
                    if self._wrap_buffer:
                        self._markdown_stream.pending += self._flush_wrap_buffer()
                    # Flush any buffered streaming text before tool output
                    if self._markdown_stream.pending:
                        self._flush_completed_stream_lines()
                        tail = self._markdown.flush_stream_tail(self._markdown_stream)
                        if tail:
                            _p(tail, end="")
                    # Update spinner to show which tool is running
                    tool_name = msg.tool_name
                    display_name = tool_name.replace("_", " ").title()
                    key_arg = _format_tool_key_arg(tool_name, msg.tool_input or {})
                    _NET_TOOLS = {"web_search", "web_fetch"}
                    if tool_name in _NET_TOOLS:
                        base = "Searching…" if tool_name == "web_search" else "Fetching…"
                        self._spinner_label = f"🌐 {base}  {key_arg}" if key_arg else f"🌐 {base}"
                    else:
                        base = f"Running {display_name}…"
                        self._spinner_label = f"{base}  {key_arg}" if key_arg else base
                    # 2C: dim tool-start banner written directly to stdout for scrollback record
                    _verb = _TOOL_VERBS.get(tool_name, tool_name.replace("_", " "))
                    _banner = f"\r\033[2K  {_DIM}·{_R} {_SFT}{_verb}{_R}"
                    if key_arg:
                        _banner += f"  {_DIM}{key_arg}{_R}"
                    sys.__stdout__.write(_banner + "\n")
                    sys.__stdout__.flush()
                    # Clear reasoning peek — tool action is starting, not free-thinking
                    self._reasoning_peek = ""
                    self._tool_call_inputs[msg.tool_call_id] = msg.tool_input
                    # Record in activity trail (duration and error filled when completed)
                    self._turn_tool_log.append((msg.tool_name, msg.tool_input, 0, None))
                    if not self._spinner_active:
                        await self._start_spinner()

                elif isinstance(msg, ToolCallCompletedEvent):
                    # Reset spinner label back to default
                    self._spinner_label = "Thinking…"
                    tool_input = self._tool_call_inputs.pop(msg.tool_call_id, None)
                    duration_ms = getattr(msg, 'duration_ms', 0)
                    error = getattr(msg, 'error', None)
                    # Update duration and error in activity trail — deferred to TurnEndedEvent
                    for i in range(len(self._turn_tool_log) - 1, -1, -1):
                        if self._turn_tool_log[i][0] == msg.tool_name and self._turn_tool_log[i][2] == 0:
                            self._turn_tool_log[i] = (msg.tool_name, self._turn_tool_log[i][1], duration_ms, error)
                            break
                    # Surface tool errors immediately — errors need to be seen right away
                    if error:
                        _render_error(error, tool_name=msg.tool_name, tool_input=tool_input)
                    elif isinstance(getattr(msg, "output", None), str) and msg.output.startswith("Error:"):
                        _render_error(
                            msg.output,
                            tool_name=getattr(msg, 'tool_name', None),
                            tool_input=tool_input,
                        )

                # ── Extended thinking ─────────────────────────────────────────

                elif isinstance(msg, ReasoningDeltaEvent):
                    if self._wrap_buffer:
                        self._markdown_stream.pending += self._flush_wrap_buffer()
                    if self._markdown_stream.pending:
                        self._flush_completed_stream_lines()
                        tail = self._markdown.flush_stream_tail(self._markdown_stream)
                        if tail:
                            _p(tail, end="")
                    if not hasattr(self, '_reasoning_started') or not self._reasoning_started:
                        self._reasoning_started = True
                        if self._after_tool:
                            _p()
                        self._after_tool = False
                        self._reasoning_buf = ""
                        self._spinner_label = "Thinking…"
                        if not self._spinner_active:
                            await self._start_spinner()
                    # Accumulate for optional verbose display; count tokens for summary
                    self._reasoning_buf += msg.delta
                    self._reasoning_token_count += max(1, len(msg.delta) // 4)
                    # 2B: Extract live reasoning peek for spinner display
                    _rbuf = self._reasoning_buf[-200:].lstrip()
                    for _sep in (". ", "? ", "! ", "\n", ", "):
                        _idx = _rbuf.rfind(_sep)
                        if 0 <= _idx < len(_rbuf) - 12:
                            _rbuf = _rbuf[_idx + len(_sep):]
                            break
                    _rbuf = _rbuf.strip().replace("\n", " ")
                    if len(_rbuf) > 72:
                        _rbuf = _rbuf[:72] + "…"
                    self._reasoning_peek = _rbuf if len(_rbuf) > 8 else ""

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
                    self._print_tool_footer(exit_code=msg.exit_code, duration_ms=msg.duration_ms)
                    self._after_tool = True
                    # Restart spinner so there's no dead space while model processes output
                    if self._task_running and not self._spinner_active:
                        await self._start_spinner()

                # ── Approval — exec ───────────────────────────────────────────

                elif isinstance(msg, ExecApprovalRequestedEvent):
                    await self._stop_spinner()
                    if self._current_buf and not self._current_buf.endswith("\n"):
                        _p()
                    self._current_buf = ""
                    if not self._task_running:
                        self._task_running = True
                    tool_label, cmd_arg = self._format_command(msg.command)
                    self._print_approval_bar(tool_label, cmd_arg)
                    self._after_tool = False
                    self._approval_active = True
                    fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
                    self._pending_approval = (msg, fut)
                    self._approval_event.set()
                    decision_str = await fut
                    # Clear immediately so main loop doesn't pick up the stale event
                    self._approval_event.clear()
                    self._pending_approval = None
                    self._approval_active = False
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

                # ── Approval — network ───────────────────────────────────────

                elif isinstance(msg, NetworkApprovalRequestedEvent):
                    await self._stop_spinner()
                    if not self._task_running:
                        self._task_running = True
                    _p()
                    _p(f"  {_bd('╭─')} {_y('Network Approval Required')}")
                    _p(f"  {_bd('│')} {_b(msg.tool_name or 'web')}")
                    _p(f"  {_bd('│')} {_s(msg.domain)}")
                    _p(f"  {_bd('│')} {_d(msg.url[:90])}")
                    _p(f"  {_bd('╰─')} {_d('allow once or trust for this session')}")
                    _p()
                    _p(f"  {_bd('[y]')} allow once  {_bd('[a]')} trust domain  {_bd('[n]')} deny {_bd('›')} ", end="")
                    ps_net = PromptSession()
                    try:
                        answer = (await ps_net.prompt_async("")).strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        answer = "n"
                    approved = answer in ("y", "yes", "a", "always")
                    approve_always = answer in ("a", "always")
                    if approve_always:
                        _p(f"  {_bd('·')} {_d(f'{msg.domain} approved for this session')}")
                    elif approved:
                        _p(f"  {_bd('·')} {_d(f'{msg.domain} allowed once')}")
                    else:
                        _p(f"  {_bd('·')} {_r(f'{msg.domain} denied')}")
                    from bob.protocol.ops import NetworkApprovalOp
                    await self._session.submit(NetworkApprovalOp(
                        url=msg.url,
                        domain=msg.domain,
                        approved=approved,
                        approve_always=approve_always,
                        request_id=msg.request_id,
                        granted=approved,
                    ))
                    if self._task_running and not self._spinner_active:
                        await self._start_spinner()

                # ── Approval — patch ──────────────────────────────────────────

                elif isinstance(msg, PatchApprovalRequestedEvent):
                    await self._stop_spinner()
                    if not self._task_running:
                        self._task_running = True
                    n = len(msg.changes)
                    self._print_approval_bar("Patch", f"{n} file(s)")
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

                # ── Sub-agent events ──────────────────────────────────────────

                elif isinstance(msg, AgentSpawnedEvent):
                    await self._stop_spinner()
                    _p(f"  {_c('⟳')} {_b(f'[{msg.name}]')} {_d('spawned')} {_s(f'· {msg.task[:70]}')}")
                    self._active_agents[msg.agent_id] = {
                        "name": msg.name,
                        "started_at": time.time(),
                        "last_activity": "",
                    }
                    if self._task_running and not self._spinner_active:
                        await self._start_spinner()

                elif isinstance(msg, AgentProgressEvent):
                    if msg.agent_id in self._active_agents:
                        self._active_agents[msg.agent_id]["last_activity"] = msg.last_activity
                    else:
                        self._active_agents[msg.agent_id] = {
                            "name": msg.name,
                            "started_at": time.time(),
                            "last_activity": msg.last_activity,
                        }

                elif isinstance(msg, AgentCompletedEvent):
                    await self._stop_spinner()
                    if msg.status == "completed":
                        icon = _g("✓")
                        status_txt = _g("done")
                    elif msg.status == "errored":
                        icon = _r("✗")
                        status_txt = _r("errored")
                    else:
                        icon = _y("·")
                        status_txt = _y(msg.status)
                    _p(
                        f"  {icon} {_b(f'[{msg.name}]')} {status_txt}"
                        f"  {_d(f'{msg.tool_use_count} tools · {msg.token_count:,} tok')}"
                    )
                    if msg.status == "errored" and msg.error:
                        _p(f"  {_r('  error:')} {_d(msg.error[:120])}")
                    self._active_agents.pop(msg.agent_id, None)
                    agent_ctrl = getattr(self._session, "agent_control", None)
                    still_active = agent_ctrl.count_active() if agent_ctrl else 0
                    if still_active > 0:
                        await self._start_spinner()
                    elif self._task_running_for_agents:
                        self._task_running = False
                        self._task_running_for_agents = False

                # ── Turn end ──────────────────────────────────────────────────

                elif isinstance(msg, TurnEndedEvent):
                    if self._wrap_buffer:
                        self._markdown_stream.pending += self._flush_wrap_buffer()
                    # Flush any remaining buffered stream text — full line render
                    if self._markdown_stream.pending:
                        self._flush_completed_stream_lines()
                        tail = self._markdown.flush_stream_tail(self._markdown_stream)
                        if tail:
                            _p(tail, end="")
                    await self._stop_spinner()
                    _print_thinking_summary(self._reasoning_token_count, self._turn_tool_log)

                    # Live-streamed replies may end without a final newline.
                    # Close the prose line before any reasoning/footer output.
                    if self._text_started and self._current_buf and not self._current_buf.endswith("\n"):
                        _p()
                    
                    # Verbose mode: show the full raw reasoning block (show_reasoning=True only)
                    if (
                        getattr(self._config, "show_reasoning", False)
                        and hasattr(self, '_reasoning_buf')
                        and self._reasoning_buf
                    ):
                        _p(f"  {_bd('╭─')} {_s('Reasoning')}")
                        lines = self._reasoning_buf.splitlines()
                        if len(lines) <= 10:
                            _p(f"  {_bd('│')} {_d('Extended thinking')}")
                            for line in lines:
                                _p(f"  {_bd('│')} {_d(line)}")
                        else:
                            _p(f"  {_bd('│')} {_d('Extended thinking')}")
                            for line in lines[:5]:
                                _p(f"  {_bd('│')} {_d(line)}")
                            _p(f"  {_bd('│')} {_d(f'... ({len(lines) - 10} more lines)')}")
                            for line in lines[-5:]:
                                _p(f"  {_bd('│')} {_d(line)}")
                        _p(f"  {_bd('╰─')} {_d('reasoning captured')}")
                    self._reasoning_buf = ""
                    self._reasoning_started = False
                    self._reasoning_token_count = 0
                    
                    # Only do a final full render if no live text was streamed.
                    if self._current_buf and not self._text_started:
                        # Clear the raw text line
                        if not self._current_buf.endswith("\n"):
                            _p()
                        rendered = self._markdown.render(self._current_buf)
                        if rendered:
                            _p(rendered)
                    elif self._after_tool and not self._current_buf:
                        # Turn ended with only tool calls and no prose — add spacing
                        _p()
                    
                    if self._text_started or self._current_buf:
                        _p()
                    
                    self._last_assistant_text = self._current_buf
                    self._current_buf  = ""
                    self._after_tool   = False
                    self._wrap_buffer = ""
                    self._wrap_column = 0
                    # Keep spinner alive if sub-agents are still running
                    _agent_ctrl = getattr(self._session, "agent_control", None)
                    if _agent_ctrl and _agent_ctrl.count_active() > 0:
                        self._task_running_for_agents = True
                        await self._start_spinner()
                    else:
                        self._task_running = False
                        self._task_running_for_agents = False
                    # Token tracking
                    in_tok  = getattr(msg, "input_tokens",  0) or 0
                    out_tok = getattr(msg, "output_tokens", 0) or 0
                    cached_tok = getattr(msg, "cached_input_tokens", 0) or 0
                    self._total_input_tokens  += in_tok
                    self._total_output_tokens += out_tok
                    self._total_cached_input_tokens += cached_tok
                    self._last_turn_tokens = {"input": in_tok, "output": out_tok, "cached": cached_tok}
                    
                    # Run post_turn hooks and surface their stdout as a status line
                    if self._config.hooks:
                        try:
                            from bob.protocol.config_types import HookEventName
                            results = await self._session.hook_runner.run_hooks(
                                HookEventName.POST_TURN,
                                {"session_id": getattr(self._session, "session_id", "")},
                            )
                            for r in results:
                                if r.stdout.strip():
                                    _p(f"  {_d(r.stdout.strip())}")
                        except Exception:
                            pass

                elif isinstance(msg, TurnInterruptedEvent):
                    await self._stop_spinner()
                    if self._current_buf and not self._current_buf.endswith("\n"):
                        _p()
                    self._current_buf  = ""
                    self._after_tool   = False
                    self._task_running = False
                    _p(f"  {_bd('·')} {_y('interrupted')}")
                    _p()

                # ── Error / warning / info ────────────────────────────────────

                elif isinstance(msg, ErrorEvent):
                    await self._stop_spinner()
                    if self._current_buf and not self._current_buf.endswith("\n"):
                        _p()
                    self._current_buf  = ""
                    self._after_tool   = False
                    self._task_running = False
                    _render_error(msg.message)
                    _p()

                elif isinstance(msg, WarningEvent):
                    _p(f"  {_bd('·')} {_y(msg.message)}")

                elif isinstance(msg, HistoryCompactedEvent):
                    _p(f"  {_bd('·')} {_d(f'context compacted · {msg.turns_removed} turns removed')}")

                elif isinstance(msg, InfoEvent):
                    _p(f"  {_bd('·')} {_s(msg.message)}")

                elif isinstance(msg, BackgroundTerminalOutputEvent):
                    _p(f"  {_bd('·')} {_d(f'[bg:{msg.terminal_id}] {msg.data.rstrip()}')}")

                elif UserInputRequestEvent is not None and isinstance(msg, UserInputRequestEvent):
                    await self._stop_spinner()
                    _p()
                    _p(f"  {_bd('╭─')} {_c('Question')}")
                    
                    # Word-wrap the prompt at terminal width
                    import textwrap
                    term_width = shutil.get_terminal_size().columns
                    wrapped_lines = textwrap.wrap(msg.prompt, width=term_width - 6)
                    for line in wrapped_lines:
                        _p(f"  {_bd('│')} {line}")
                    _p(f"  {_bd('╰─')} {_d('respond to continue')}")
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
                            answer = await ps_tmp.prompt_async(ANSI(f"  {_bd('›')} "))
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
                    _p(f"  {_bd('╭─')} {_c('Plan Summary')}")
                    
                    # Word-wrap and display plan
                    import textwrap
                    term_width = shutil.get_terminal_size().columns
                    wrapped_lines = textwrap.wrap(msg.plan_summary, width=term_width - 6)
                    for line in wrapped_lines:
                        _p(f"  {_bd('│')} {line}")
                    
                    _p(f"  {_bd('╰─')} {_d('approval unlocks mutating tools')}")
                    _p()
                    _p(f"  {_bd('·')} {_y('This will unlock write tools and file modifications.')}")
                    _p()
                    
                    # Prompt for approval
                    try:
                        ps_tmp = PromptSession()
                        response = await ps_tmp.prompt_async(
                            ANSI(f"  {_bd('›')} approve plan? (y/n/feedback): ")
                        )
                    except (EOFError, KeyboardInterrupt):
                        response = "n"
                    
                    response = response.strip().lower()
                    
                    if response in ('y', 'yes'):
                        from bob.protocol.ops import PlanApprovalOp
                        await self._session.submit(PlanApprovalOp(approved=True))
                        _p(f"  {_bd('·')} {_g('plan approved')}")
                    elif response in ('n', 'no'):
                        from bob.protocol.ops import PlanApprovalOp
                        await self._session.submit(PlanApprovalOp(approved=False))
                        _p(f"  {_bd('·')} {_r('plan rejected')}")
                    else:
                        # Treat as feedback
                        from bob.protocol.ops import PlanApprovalOp
                        await self._session.submit(
                            PlanApprovalOp(approved=False, feedback=response)
                        )
                        _p(f"  {_bd('·')} {_y('plan rejected with feedback')}")
                    
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

                elif isinstance(msg, McpStartupStatusEvent):
                    if msg.failed:
                        failed_servers = ", ".join(msg.failed)
                        _p(f"  {_bd('·')} {_y(f'MCP: {len(msg.failed)} server(s) failed: {failed_servers}')}")

                elif isinstance(msg, McpServersRefreshedEvent):
                    connected_servers = ", ".join(msg.connected) or "none"
                    failed_servers = ", ".join(msg.failed) or "none"
                    _p(
                        f"  {_bd('·')} "
                        f"{_d(f'MCP refreshed · connected: {connected_servers} · failed: {failed_servers}')}"
                    )

                elif isinstance(msg, McpToolsListedEvent):
                    if not msg.tools:
                        _p(f"  {_d('No MCP tools available')}")
                    else:
                        _p(f"  {_bd('MCP tools')} ({len(msg.tools)})")
                        for t in msg.tools:
                            _p(f"    {_c(t['server_name'])}{_d('/')}{t['name']}")
                            if t.get('description'):
                                _p(f"      {_d(t['description'][:80])}")

                elif isinstance(msg, SkillsListedEvent):
                    def _entry_skills(entry):
                        if isinstance(entry, dict):
                            return entry.get("skills", [])
                        return getattr(entry, "skills", [])

                    def _skill_value(skill, key, default=None):
                        if isinstance(skill, dict):
                            return skill.get(key, default)
                        return getattr(skill, key, default)

                    total = sum(len(_entry_skills(e)) for e in msg.entries)
                    if total == 0:
                        _p(f"  {_d('No skills found')}")
                    else:
                        _p(f"  {_bd('Skills')} ({total})")
                        for entry in msg.entries:
                            for skill in _entry_skills(entry):
                                invocable = " [/]" if _skill_value(skill, "user_invocable", False) else ""
                                name = _skill_value(skill, "name", "?")
                                description = _skill_value(skill, "description", "")[:70]
                                _p(f"    {_c(name)}{_d(invocable)} — {description}")

            except Exception as exc:
                self._log_event_handler_error(msg, exc)

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
            _p()
            _p(f"  {_d('goodbye')}")
            _p()
            return True

        elif cmd == SlashCommand.CLEAR:
            os.system("cls" if sys.platform == "win32" else "clear")
            await self._session.reset()
            self._pending_context_items.clear()
            self._last_assistant_text = ""
            self._print_header()
            _p(f"  {_d('cleared screen, chat history, and context window for this session')}")
            _p()

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
            sub = args.strip().lower() if args else ""
            if sub == "refresh":
                from bob.protocol.ops import RefreshMcpServersOp
                _p(f"  {_d('refreshing MCP servers…')}")
                await self._session.submit(RefreshMcpServersOp())
            else:
                from bob.protocol.ops import ListMcpToolsOp
                server_filter = args.strip() if args and args.strip() != "list" else None
                await self._session.submit(ListMcpToolsOp(server_name=server_filter))
                _p(f"  {_d('listing MCP tools…')}")

        elif cmd == SlashCommand.SKILLS:
            sub = args.strip().lower() if args else ""
            if sub == "list" or not sub:
                from bob.protocol.ops import ListSkillsOp
                await self._session.submit(ListSkillsOp(cwd=str(self._session.cwd)))
                _p(f"  {_d('listing skills…')}")
            else:
                # Treat as skill name to invoke
                skill_name, _, skill_args = args.strip().partition(" ")
                await self._session.invoke_skill(skill_name.strip(), skill_args.strip())
                _p(f"  {_d(f'invoking skill: {skill_name}…')}")

        elif cmd == SlashCommand.PLUGINS:
            from bob.plugins.manager import PluginsManager

            plugins = []
            seen: set[str] = set()
            plugin_roots = [
                ("user", self._session.bob_home / "plugins"),
                ("repo", self._session.cwd / ".bob" / "plugins"),
            ]
            for scope, root in plugin_roots:
                pm = PluginsManager(root)
                for plugin in pm.list_plugins():
                    key = plugin.name.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    plugins.append((scope, plugin))

            if not plugins:
                _p(f"  {_d('No plugins installed')}")
            else:
                _p(f"  {_bd('Plugins')} ({len(plugins)})")
                for scope, plugin in plugins:
                    status = "" if plugin.enabled else " [disabled]"
                    _p(f"    {_c(plugin.name)}{_d(status)} {_d(f'[{scope}]')} — {plugin.description[:70]}")

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
                _p(f"  {_d('running review…')}")
                review = await self._quick_model_turn(
                    "Review the following git diff summary and identify bugs, "
                    "behavioral regressions, security issues, and missing tests.\n\n"
                    f"{diff}"
                )
                if not review.strip():
                    _p(f"  {_d('no review output')}")
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
                shown = sessions[:20]
                _p()
                for i, s in enumerate(shown, 1):
                    label = (getattr(s, "name", None) or "").strip() or getattr(s, "id", "?")[:12]
                    sid = getattr(s, "id", "?")[:8]
                    model = getattr(s, "model", None) or "unknown-model"
                    updated = getattr(s, "updated_at", "") or ""
                    preview = (getattr(s, "preview", None) or "").strip()
                    line = f"  {_d(str(i) + '.')}  {label} [{sid}] ({model})"
                    if updated:
                        line += f"  {updated[:19]}"
                    _p(line)
                    if preview:
                        _p(f"      {_d(preview[:120])}")
                _p()

                raw = args.strip()
                if not raw:
                    try:
                        ps = PromptSession()
                        raw = (await ps.prompt_async("  select number, id prefix, or search text: ")).strip()
                    except Exception:
                        raw = ""
                if not raw:
                    _p(f"  {_d('cancelled')}")
                else:
                    selected = None
                    # Numeric choice
                    if raw.isdigit():
                        idx = int(raw) - 1
                        if 0 <= idx < len(shown):
                            selected = shown[idx]
                    # Direct/partial id match
                    if selected is None:
                        id_matches = [s for s in sessions if str(getattr(s, "id", "")).startswith(raw)]
                        if len(id_matches) == 1:
                            selected = id_matches[0]
                    # Name/preview search fallback
                    if selected is None:
                        q = raw.lower()
                        text_matches = []
                        for s in sessions:
                            hay = " ".join([
                                str(getattr(s, "name", "") or ""),
                                str(getattr(s, "cwd", "") or ""),
                                str(getattr(s, "preview", "") or ""),
                                str(getattr(s, "id", "") or ""),
                            ]).lower()
                            if q in hay:
                                text_matches.append(s)
                        if len(text_matches) == 1:
                            selected = text_matches[0]
                        elif len(text_matches) > 1:
                            _p(f"  {_y('⚠')} multiple matches; use a number or longer id prefix")
                            selected = None

                    if selected is None:
                        _p(f"  {_y('⚠')} no matching saved session")
                    else:
                        await self._session.resume(
                            selected.path,
                            session_id=getattr(selected, "id", None),
                        )
                        label = getattr(selected, "name", None) or getattr(selected, "id", "?")[:12]
                        _p(f"  {_d(f'resumed: {label}')}")

        elif cmd == SlashCommand.DEBUG_M_DROP:
            from bob.protocol.ops import DropMemoriesOp
            await self._session.submit(DropMemoriesOp())
            _p(f"  {_d('dropped all memories')}")

        # ── Phase 1: help, model, effort, cost, usage ─────────────────────────

        elif cmd == SlashCommand.HELP:
            from rich.console import Console
            from rich.table import Table
            import io
            
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
                ("Workflow",    [SlashCommand.PLAN, SlashCommand.MCP, SlashCommand.SKILLS, SlashCommand.HOOKS]),
                ("System",      [SlashCommand.DOCTOR, SlashCommand.INIT, SlashCommand.FEEDBACK,
                                  SlashCommand.QUIT]),
            ]
            
            for group, cmds in groups:
                table = Table(show_header=False, box=None, padding=(0, 2))
                table.add_column("Command", style="cyan", no_wrap=True)
                table.add_column("Description", style="dim")
                
                for c in cmds:
                    desc = COMMAND_DESCRIPTIONS.get(c, "")
                    table.add_row(f"/{c.value}", desc)
                
                # Render table to string
                string_io = io.StringIO()
                console = Console(file=string_io, force_terminal=True, width=shutil.get_terminal_size((120, 24)).columns)
                console.print(f"[bold]{group}[/bold]")
                console.print(table)
                
                # Print the rendered output
                output = string_io.getvalue()
                for line in output.splitlines():
                    _p(f"  {line}")
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
            runtime = self._session.describe_model_runtime(self._config.model)
            _p()
            checks: list[tuple[bool, str]] = []

            missing_auth = runtime.get("missing_auth", [])
            checks.append((not missing_auth, f"auth configured for provider '{runtime['provider']}'"))

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

            _p("  " + _d(f"model: {runtime['requested_model']}"))
            _p("  " + _d(f"provider: {runtime['provider']}  route: {runtime['route']}  support: {runtime['support_level']}"))
            if runtime.get("canonical_model") and runtime["canonical_model"] != runtime["requested_model"]:
                _p("  " + _d(f"canonical: {runtime['canonical_model']}"))

            for ok, label in checks:
                icon = _g("✓") if ok else _r("✗")

                _p(f"  {icon} {label}")
            if missing_auth:
                _p(f"  {_y('WARN')} Missing provider settings: {', '.join(missing_auth)}")
            for note in runtime.get("notes", [])[:3]:
                _p(f"  {_d(note)}")

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
                            
                            status_label = self._status_label(status)
                            status_icon = self._status_icon(status_label)
                            
                            # Color-code by priority
                            if priority == 'high':
                                priority_text = _r(priority)
                            elif priority == 'medium':
                                priority_text = _y(priority)
                            else:
                                priority_text = _d(priority)
                            
                            _p(f"  {status_icon} [{_cy(task_id)}] {title}")
                            _p(f"    {_d('Status:')} {status_label} {_d('|')} {_d('Priority:')} {priority_text}")
                        
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

        elif cmd == SlashCommand.BOB_IN_CHROME:
            bridge = getattr(self._session, "_chrome_bridge", None)
            _p()
            if bridge is None:
                _p(f"  {_r('✗')} Chrome bridge not available in this session")
            else:
                action = (args.strip().lower() or "status")
                if action in ("off", "disable"):
                    bridge.disable()
                    _p(f"  {_d('Chrome bridge disabled — bob will not control the browser')}")
                elif action in ("on", "enable"):
                    bridge.enable()
                    if bridge.is_connected:
                        _p(f"  {_g('✓')} Chrome bridge enabled — extension is connected")
                    else:
                        _p(f"  {_y('○')} Chrome bridge enabled — waiting for Chrome extension on ws://localhost:{bridge.port}")
                else:
                    if bridge.is_connected:
                        _p(f"  {_g('✓')} Chrome extension connected  (ws://localhost:{bridge.port})")
                        _p(f"  {_d('bob can now control your browser')}")
                    elif bridge._enabled:
                        _p(f"  {_y('○')} Chrome bridge listening on ws://localhost:{bridge.port}")
                        _p(f"  {_d('Open the bob Chrome extension in Chrome to connect')}")
                    else:
                        _p(f"  {_r('○')} Chrome bridge is disabled — run /bob-in-chrome on to enable")
                    _p()
                    _p(f"  {_d('Usage:  /bob-in-chrome [on|off]')}")
            _p()

        elif cmd == SlashCommand.CONFIG:
            _p()
            _p(f"  {_b('Configuration:')}")
            _p()
            config_items = [
                ("model", self._config.model),
                ("reasoning_effort", self._config.reasoning_effort.value),
                ("output_style", self._config.output_style.value),
                ("sandbox_mode", self._config.sandbox_mode.value),
                ("ask_for_approval", self._config.ask_for_approval.value),
                ("network_access", str(self._config.network_access)),
                ("enable_memories", str(self._config.enable_memories)),
                ("enable_skills", str(self._config.enable_skills)),
                ("show_reasoning", str(self._config.show_reasoning)),
            ]
            for key, val in config_items:
                _p(f"  {_d(f'{key:<20}')}  {val}")
            _p()
            _p(f"  {_d('Config file: ~/.bob/config.toml')}")
            _p(f"  {_d('Edit with: /config edit')}")
            _p()

        elif cmd == SlashCommand.STATS:
            _p()
            _p(f"  {_b('Session Statistics:')}")
            _p()
            _p(f"  {_d('Total input tokens')}   {self._total_input_tokens:>10,}")
            if self._total_cached_input_tokens > 0:
                _p(f"  {_g('Cached tokens')}       {self._total_cached_input_tokens:>10,}")
            _p(f"  {_d('Total output tokens')}  {self._total_output_tokens:>10,}")
            _p(f"  {_d('Total tokens')}         {self._total_input_tokens + self._total_output_tokens:>10,}")
            _p()
            # Calculate cost if possible
            if hasattr(self._session, 'analytics') and self._session.analytics:
                cost = self._session.analytics.session_cost_usd
                if cost > 0:
                    _p(f"  {_d('Estimated cost')}       ${cost:.4f}")
                    _p()
                changed_files = list(self._session.analytics.last_turn_changed_files or [])
                _p(f"  {_d('Files changed last turn')} {len(changed_files):>6}")
                for path in changed_files[:10]:
                    _p(f"    {_d('-')} {path}")
                if len(changed_files) > 10:
                    _p(f"    {_d('...')} {len(changed_files) - 10} more")
                _p()

        elif cmd == SlashCommand.SESSION:
            _p()
            _p(f"  {_b('Session Information:')}")
            _p()
            _p(f"  {_d('Session ID')}     {self._session.session_id}")
            _p(f"  {_d('Model')}          {self._config.model}")
            _p(f"  {_d('Working dir')}    {Path.cwd()}")
            _p(f"  {_d('Sandbox mode')}   {self._config.sandbox_mode.value}")
            _p(f"  {_d('Total tokens')}   {self._total_input_tokens + self._total_output_tokens:,}")
            _p()

        elif cmd == SlashCommand.MEMORY:
            memory_path = Path.home() / ".bob" / "memory.md"
            if not args.strip():
                # Show memory contents
                if memory_path.exists():
                    content = memory_path.read_text(encoding="utf-8")
                    _p()
                    _p(f"  {_b('Memory Contents:')}")
                    _p()
                    for line in content.splitlines()[:50]:  # Show first 50 lines
                        _p(f"  {line}")
                    _p()
                else:
                    _p(f"  {_d('No memory file found')}")
            elif args.strip() == "edit":
                # Open in editor
                editor = os.environ.get("EDITOR", "nano")
                try:
                    memory_path.parent.mkdir(parents=True, exist_ok=True)
                    subprocess.run([editor, str(memory_path)])
                    _p(f"  {_g('✓')} Memory file edited")
                except Exception as exc:
                    _p(f"  {_r('✗')} Failed to open editor: {exc}")
            elif args.strip() == "clear":
                # Clear memory
                try:
                    if memory_path.exists():
                        memory_path.unlink()
                    _p(f"  {_g('✓')} Memory cleared")
                except Exception as exc:
                    _p(f"  {_r('✗')} Failed to clear memory: {exc}")
            else:
                _p(f"  {_y('⚠')} usage: /memory [edit|clear]")

        elif cmd == SlashCommand.SHARE:
            # Export as self-contained HTML
            import time as _time
            dest = args.strip()
            if not dest:
                ts = int(_time.time())
                dest = str(Path.home() / f"bob-session-{ts}.html")
            try:
                items = self._session.context_manager.raw_items()
                html_parts = [
                    "<!DOCTYPE html>",
                    "<html><head>",
                    "<meta charset='utf-8'>",
                    "<title>Bob Session</title>",
                    "<style>",
                    "body { font-family: system-ui, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; }",
                    ".user { background: #f0f0f0; padding: 15px; margin: 10px 0; border-radius: 5px; }",
                    ".assistant { background: #e8f4f8; padding: 15px; margin: 10px 0; border-radius: 5px; }",
                    "pre { background: #2d2d2d; color: #f8f8f2; padding: 10px; border-radius: 3px; overflow-x: auto; }",
                    "</style>",
                    "</head><body>",
                    "<h1>Bob Session Export</h1>",
                ]
                
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
                    
                    # Escape HTML
                    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    
                    if role == "user":
                        html_parts.append(f"<div class='user'><strong>User:</strong><br>{text}</div>")
                    elif role == "assistant":
                        html_parts.append(f"<div class='assistant'><strong>Bob:</strong><br>{text}</div>")
                
                html_parts.append("</body></html>")
                
                Path(dest).write_text("\n".join(html_parts), encoding="utf-8")
                _p(f"  {_g('✓')} Exported to: {dest}")
                
                # Try to open in browser
                try:
                    import webbrowser
                    webbrowser.open(f"file://{Path(dest).absolute()}")
                    _p(f"  {_d('Opened in browser')}")
                except Exception:
                    pass
            except Exception as exc:
                _p(f"  {_r('✗')} {exc}")

        elif cmd == SlashCommand.ISSUE:
            # Create GitHub issue
            title = args.strip()
            if not title:
                _p(f"  {_y('⚠')} usage: /issue <title>")
            else:
                try:
                    # Check if gh CLI is available
                    if not shutil.which("gh"):
                        _p(f"  {_r('✗')} GitHub CLI (gh) not found. Install from https://cli.github.com/")
                        return False
                    
                    # Get summary of current session
                    _p(f"  {_d('Generating issue body from session context…')}")
                    body = await self._quick_model_turn(
                        f"Create a concise GitHub issue body for: {title}\n\n"
                        "Include: problem description, steps to reproduce (if applicable), "
                        "and any relevant context from our conversation. "
                        "Format as markdown. Be brief but complete."
                    )
                    
                    # Create issue
                    result = subprocess.run(
                        ["gh", "issue", "create", "--title", title, "--body", body],
                        capture_output=True, text=True, cwd=Path.cwd(), timeout=30,
                    )
                    
                    if result.returncode == 0:
                        # Extract URL from output
                        url = result.stdout.strip().split()[-1] if result.stdout else ""
                        _p(f"  {_g('✓')} Issue created: {url}")
                    else:
                        _p(f"  {_r('✗')} Failed to create issue: {result.stderr.strip()}")
                except Exception as exc:
                    _p(f"  {_r('✗')} {exc}")

        elif cmd == SlashCommand.PR_COMMENTS:
            # Fetch PR review comments
            pr_num = args.strip()
            if not pr_num:
                _p(f"  {_y('⚠')} usage: /pr_comments <pr_number>")
            else:
                try:
                    # Check if gh CLI is available
                    if not shutil.which("gh"):
                        _p(f"  {_r('✗')} GitHub CLI (gh) not found. Install from https://cli.github.com/")
                        return False
                    
                    _p(f"  {_d(f'Fetching PR #{pr_num} comments…')}")
                    result = subprocess.run(
                        ["gh", "pr", "view", pr_num, "--json", "comments,reviews"],
                        capture_output=True, text=True, cwd=Path.cwd(), timeout=15,
                    )
                    
                    if result.returncode == 0:
                        import json
                        data = json.loads(result.stdout)
                        comments = data.get("comments", [])
                        reviews = data.get("reviews", [])
                        
                        # Format as context
                        context_parts = [f"# PR #{pr_num} Comments\n"]
                        
                        for comment in comments:
                            author = comment.get("author", {}).get("login", "unknown")
                            body = comment.get("body", "")
                            context_parts.append(f"## Comment by {author}\n{body}\n")
                        
                        for review in reviews:
                            author = review.get("author", {}).get("login", "unknown")
                            body = review.get("body", "")
                            state = review.get("state", "")
                            context_parts.append(f"## Review by {author} ({state})\n{body}\n")
                        
                        context_text = "\n".join(context_parts)
                        self._pending_context_items.append(context_text)
                        
                        _p(f"  {_g('✓')} Added {len(comments)} comments and {len(reviews)} reviews to context")
                    else:
                        _p(f"  {_r('✗')} Failed to fetch PR: {result.stderr.strip()}")
                except Exception as exc:
                    _p(f"  {_r('✗')} {exc}")

        elif cmd == SlashCommand.THEME:
            # Theme switching (basic implementation)
            theme = args.strip().lower()
            if not theme:
                _p(f"  {_d('Current theme: dark (default)')}")
                _p(f"  {_d('Available: dark, light, no-color')}")
            elif theme in ("dark", "light", "no-color"):
                if theme == "no-color":
                    self._config.no_color = True
                    _p(f"  {_d('Color output disabled')}")
                else:
                    self._config.no_color = False
                    _p(f"  {_d(f'Theme set to: {theme}')}")
                    _p(f"  {_y('⚠')} Full theme support not yet implemented")
            else:
                _p(f"  {_r('✗')} Invalid theme: {theme}")
                _p(f"  {_d('Available: dark, light, no-color')}")

        else:
            _p(f"  {_y('⚠')} /{cmd.value} not yet implemented")

        return False

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def _busy_wait(self, ps: PromptSession) -> None:
        """Spin while the model is working.

        Called AFTER input_task is fully cancelled (prompt torn down), so it
        is safe to start the spinner here without overlapping with ❯.
        Handles approval prompts inline.  Ctrl+C sends an InterruptOp.
        Arrow Up/Down opens the agent inspector (Windows only via msvcrt).
        """
        await self._start_spinner()
        _inspector_open = False
        _inspector_sel = 0
        _inspector_lines = 0
        _inspector_refresh = 0.0
        try:
            while self._task_running or self._pending_approval is not None:
                if self._pending_approval is not None:
                    # Spinner is stopped by the event consumer before printing the
                    # approval header; just handle the prompt here.
                    _, fut = self._pending_approval
                    _approval_prompt = ANSI(
                        f"  {_bd('[y]')} approve  "
                        f"{_bd('[a]')} session  "
                        f"{_bd('[n]')} deny  "
                        f"{_bd('[s]')} abort  "
                        f"{_bd('›')} "
                    )
                    try:
                        raw = await PromptSession().prompt_async(_approval_prompt)
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
                    # Arrow-key agent inspector (Windows only via msvcrt)
                    try:
                        import msvcrt
                        while msvcrt.kbhit():
                            ch = msvcrt.getch()
                            if ch in (b'\xe0', b'\x00'):
                                ch2 = msvcrt.getch()
                                if ch2 in (b'H', b'P'):  # Up / Down arrow
                                    if not _inspector_open:
                                        await self._stop_spinner()
                                        _inspector_sel = 0
                                        _inspector_lines = self._draw_inspector_panel(_inspector_sel)
                                        _inspector_open = True
                                        _inspector_refresh = time.time()
                                    else:
                                        _agent_ctrl = getattr(self._session, "agent_control", None)
                                        _recs = [r for r in _agent_ctrl.registry._agents.values() if not r.status.is_terminal] if _agent_ctrl else []
                                        if ch2 == b'H':
                                            _inspector_sel = max(0, _inspector_sel - 1)
                                        else:
                                            _inspector_sel = min(max(0, len(_recs) - 1), _inspector_sel + 1)
                                        self._clear_inspector_panel(_inspector_lines)
                                        _inspector_lines = self._draw_inspector_panel(_inspector_sel)
                            elif ch == b'\r' and _inspector_open:
                                self._clear_inspector_panel(_inspector_lines)
                                _inspector_lines = 0
                                self._print_agent_detail(_inspector_sel)
                                _inspector_open = False
                                if self._task_running and not self._spinner_active:
                                    await self._start_spinner()
                            elif ch in (b'\x1b', b'q', b'Q') and _inspector_open:
                                self._clear_inspector_panel(_inspector_lines)
                                _inspector_lines = 0
                                _inspector_open = False
                                if self._task_running and not self._spinner_active:
                                    await self._start_spinner()
                    except ImportError:
                        pass

                    # Refresh inspector panel once per second (live timer updates)
                    if _inspector_open:
                        _now_t = time.time()
                        if _now_t - _inspector_refresh > 1.0:
                            _agent_ctrl = getattr(self._session, "agent_control", None)
                            _recs = [r for r in _agent_ctrl.registry._agents.values() if not r.status.is_terminal] if _agent_ctrl else []
                            if _recs:
                                _inspector_sel = min(_inspector_sel, len(_recs) - 1)
                                self._clear_inspector_panel(_inspector_lines)
                                _inspector_lines = self._draw_inspector_panel(_inspector_sel)
                            else:
                                self._clear_inspector_panel(_inspector_lines)
                                _inspector_lines = 0
                                _inspector_open = False
                                if self._task_running and not self._spinner_active:
                                    await self._start_spinner()
                            _inspector_refresh = _now_t

                    try:
                        await asyncio.sleep(0.05)
                    except KeyboardInterrupt:
                        self._exit_requested.set()
                        return
        finally:
            if _inspector_open:
                self._clear_inspector_panel(_inspector_lines)
            await self._stop_spinner()

    async def _load_model_picker_models(self) -> list[dict]:
        """Return model metadata for the interactive picker."""
        from bob.llm.catalog import get_catalog
        from bob.llm.compatibility import get_model_compatibility, get_picker_seed_models

        catalog = get_catalog()
        merged: dict[str, dict] = {
            row["model_id"]: dict(row) for row in get_picker_seed_models()
        }

        if catalog.is_populated():
            for row in catalog.list_models(status="active"):
                compat = get_model_compatibility(row["model_id"], catalog_provider=row.get("provider"))
                merged[row["model_id"]] = {
                    **merged.get(row["model_id"], {}),
                    **row,
                    "route": compat.route.value,
                    "support_level": compat.support_level.value,
                }

        try:
            listed = await self._session.client.list_models()
        except Exception:
            listed = []

        for model_id in listed:
            compat = get_model_compatibility(model_id)
            merged[model_id] = {
                **merged.get(model_id, {}),
                "model_id": model_id,
                "provider": compat.provider,
                "family": compat.provider,
                "route": compat.route.value,
                "support_level": compat.support_level.value,
            }

        order = {"stable": 0, "experimental": 1, "catalog_only": 2, "unknown": 3}
        return sorted(
            merged.values(),
            key=lambda row: (
                order.get(str(row.get("support_level", "unknown")), 9),
                str(row.get("provider", "")),
                str(row.get("model_id", "")),
            ),
        )

    def _apply_selected_model(self, model_name: str) -> None:
        """Keep the visible config and session runtime model in sync."""
        self._config = self._config.model_copy(update={"model": model_name})
        self._session.config = self._session.config.model_copy(update={"model": model_name})
        self._session.client = self._session._make_client(model_name)
        # Persist the choice to the user-global config so it survives across sessions.
        from bob.config.editor import set_value
        try:
            set_value("model", model_name)
        except Exception:
            pass  # Best-effort: don't crash the UI if the config file can't be written.

    def _persist_current_model(self) -> None:
        """Save the currently active model to the user-global config on exit."""
        from bob.config.editor import set_value
        try:
            set_value("model", self._config.model)
        except Exception:
            pass  # Best-effort: don't crash on exit if the config file can't be written.

    async def _handle_model_picker(self, search: str) -> None:
        """Interactive /model picker with immediate searchable dropdown."""
        from bob.llm.catalog import get_catalog

        catalog = get_catalog()
        current = self._config.model
        models = await self._load_model_picker_models()

        if not models:
            if search:
                self._apply_selected_model(search)
                _p(f"  {_g('OK')} Model set to: {_b(search)}")
            else:
                _p(f"  current model: {_b(current)}")
                _p(f"  {_d('No model catalog available and the provider did not return a model list.')}")
                _p(f"  {_d('You can still set a model manually with: /model <name>')}")
            return

        completer = _ModelPickerCompleter(models=models, current_model=current)
        kb = KeyBindings()

        @kb.add(Keys.Down)
        def _(event):
            buf = event.current_buffer
            if buf.complete_state:
                buf.complete_next()
            else:
                buf.start_completion(select_first=True)

        @kb.add(Keys.Up)
        def _(event):
            buf = event.current_buffer
            if buf.complete_state:
                buf.complete_previous()
            else:
                buf.start_completion(select_first=True)

        @kb.add(Keys.Tab)
        def _(event):
            buf = event.current_buffer
            if buf.complete_state:
                buf.complete_next()
            else:
                buf.start_completion(select_first=True)

        @kb.add(Keys.ControlN)
        def _(event):
            buf = event.current_buffer
            if buf.complete_state:
                buf.complete_next()
            else:
                buf.start_completion(select_first=True)

        @kb.add(Keys.ControlP)
        def _(event):
            buf = event.current_buffer
            if buf.complete_state:
                buf.complete_previous()
            else:
                buf.start_completion(select_first=True)

        @kb.add(Keys.Enter)
        def _(event):
            buf = event.current_buffer
            state = buf.complete_state
            text = buf.text.strip()
            if state and state.completions and (state.current_completion is not None or text):
                completion = state.current_completion or state.completions[0]
                buf.apply_completion(completion)
            buf.validate_and_handle()

        ps = PromptSession(
            completer=completer,
            complete_while_typing=True,
            complete_in_thread=True,
            complete_style="MULTI_COLUMN",
            key_bindings=kb,
            history=InMemoryHistory(),
        )

        _p()
        _p(f"  {_d('Model picker: type to filter, use Up/Down, Enter to select, empty Enter to cancel.')}")
        _p(f"  {_d(f'Current model: {current}')}")

        try:
            raw = await ps.prompt_async(
                ANSI(f"  {_c('model')} {_cb('>')} "),
                default=search,
                pre_run=lambda: get_app().current_buffer.start_completion(select_first=False),
            )
            chosen = raw.strip()
        except (KeyboardInterrupt, EOFError):
            _p(f"  {_d('cancelled')}")
            return

        if not chosen:
            _p(f"  {_d('cancelled')}")
            return

        self._apply_selected_model(chosen)

        info = catalog.get_model(chosen) if catalog.is_populated() else None
        if info:
            ctx = info.get("context_window")
            inp = info.get("input_price_per_1m")
            out = info.get("output_price_per_1m")
            ctx_s = f"  context: {ctx // 1000}K" if ctx else ""
            pr_s = (
                f"  ${inp:.2f}/${out:.2f} per 1M"
                if inp is not None and out is not None
                else ""
            )
            _p(f"  {_g('OK')} Model set to: {_b(chosen)}{_d(ctx_s + pr_s)}")
        else:
            _p(f"  {_g('OK')} Model set to: {_b(chosen)}")

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

            @kb.add("/")
            def _(event):
                """Typing / at the start of a prompt immediately opens slash-command completion."""
                buf = event.current_buffer
                buf.insert_text("/")
                if buf.text == "/" and buf.cursor_position == 1:
                    buf.start_completion(select_first=False)
            
            session = PromptSession(
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

            def _refresh_slash_menu(_buff) -> None:
                text = session.default_buffer.text
                if text.startswith("/") and " " not in text:
                    session.default_buffer.start_completion(select_first=False)

            session.default_buffer.on_text_changed += _refresh_slash_menu
            return session

        ps: PromptSession = _make_session()

        self._print_header()   # rich Panel — before patch_stdout

        with patch_stdout():
            global _UI_LOG_SINK
            _UI_LOG_SINK = self._log_ui_line
            self._log_ui_line("[header] welcome header rendered")
            self._log_ui_line(f"[session] cwd={self._session.cwd}")
            self._log_ui_line(f"[session] model={self._config.model}")
            _p(f"  {_d(f'log: {self._session_log_path}')}")
            if hasattr(self._session, "action_log_path"):
                _p(f"  {_d(f'actions: {self._session.action_log_path}')}")
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

                    # ── ❯ prompt — bordered box, interruptible by wake events ─
                    try:
                        text = await self._prompt_with_box(ps)
                    except (EOFError, KeyboardInterrupt):
                        await self._stop_spinner()
                        _p()
                        _p(f"  {_d('goodbye')}")
                        _p()
                        self._exit_requested.set()
                        break

                    if text is None:
                        continue   # wake event fired — re-enters _busy_wait

                    text = text.strip()
                    if not text:
                        continue

                    if text.startswith("/"):
                        cmd, args = parse_command(text)
                        if cmd is None:
                            _p(f"  {_r('✗')} unknown command: {text}")
                            continue
                        self._log_ui_line(f"[input] slash={text}")
                        if await self._dispatch_slash(cmd, args):
                            break

                    elif text.startswith("!"):
                        shell_cmd = text[1:].strip()
                        if shell_cmd:
                            self._log_ui_line(f"[input] shell=!{shell_cmd}")
                            from bob.protocol.ops import RunUserShellCommandOp
                            await self._session.submit(
                                RunUserShellCommandOp(command=shell_cmd)
                            )

                    else:
                        self._log_ui_line(f"[input] user={text}")
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
                        # Parse @image.png tokens out of the text
                        from bob.protocol.items import ImageUserInput as _ImgInput
                        cleaned_text, image_paths = _parse_at_images(full_text)
                        items: list = [TextUserInput(type="text", text=cleaned_text or full_text)]
                        for img_path in image_paths:
                            items.append(_ImgInput(type="image", path=img_path))
                            _p(f"  {_d(f'📎 attached: {img_path.name}')}")
                        await self._session.submit(UserTurnOp(items=items))
                        
                        # Reset thinking budget after turn
                        if self._config.thinking_budget_tokens > 0:
                            self._config = self._config.model_copy(update={"thinking_budget_tokens": 0})

                    if self._done.is_set() or self._exit_requested.is_set():
                        break

            finally:
                _UI_LOG_SINK = None
                try:
                    event_task.cancel()
                    try:
                        await event_task
                    except asyncio.CancelledError:
                        pass
                except BaseException:
                    pass
                try:
                    self._persist_current_model()
                except BaseException:
                    pass
                try:
                    self._log_ui_line("[session] log closed")
                    self._session_log_handle.close()
                except BaseException:
                    pass


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_interface(session, config: BobConfig) -> str:
    """Called from bob/cli/main.py after BobSession is started.

    Returns the model ID that was active at the end of the session so the
    caller can persist it as the default for future conversations.
    """
    interface = Interface(session=session, config=config)
    await interface.run()
    return interface._config.model
