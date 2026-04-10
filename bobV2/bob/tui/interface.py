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
import html
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


# ── Markdown → ANSI renderer ──────────────────────────────────────────────────

# ANSI extras not in the palette above
_ITA  = "\033[3m"   # italic
_UND  = "\033[4m"   # underline
_STR  = "\033[9m"   # strikethrough
_CODE_BG = "\033[48;5;236m"   # dark-grey background for inline code
_CODE_FG = "\033[96m"          # bright-cyan text for inline code
_H1_FG   = "\033[97m"          # bright white
_H2_FG   = "\033[97m"          # bright white
_H3_FG   = "\033[36m"          # cyan


def _inline_md(text: str) -> str:
    """Apply inline ANSI markdown (bold, italic, code, strikethrough) to *text*."""
    # bold+italic  ***text***
    text = re.sub(r'\*\*\*(.+?)\*\*\*', lambda m: f"{_BLD}{_ITA}{m.group(1)}{_R}", text)
    # bold  **text**
    text = re.sub(r'\*\*(.+?)\*\*', lambda m: f"{_BLD}{m.group(1)}{_R}", text)
    # italic  *text*  (not preceded/followed by another *)
    text = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', lambda m: f"{_ITA}{m.group(1)}{_R}", text)
    # italic  _text_  (not preceded/followed by another _)
    text = re.sub(r'(?<!_)_([^_\n]+?)_(?!_)', lambda m: f"{_ITA}{m.group(1)}{_R}", text)
    # inline code  `text`
    text = re.sub(r'`([^`\n]+?)`', lambda m: f"{_CODE_BG}{_CODE_FG}{m.group(1)}{_R}", text)
    # strikethrough  ~~text~~
    text = re.sub(r'~~(.+?)~~', lambda m: f"{_STR}{m.group(1)}{_R}", text)
    return text


def _render_md_line(line: str) -> str:
    """Render a single complete line with full markdown formatting."""
    # H1  # Heading
    if re.match(r'^# ', line):
        return f"{_BLD}{_H1_FG}{_UND}{_inline_md(line[2:])}{_R}"
    # H2  ## Heading
    if re.match(r'^## ', line):
        return f"{_BLD}{_H2_FG}{_inline_md(line[3:])}{_R}"
    # H3  ### Heading
    if re.match(r'^### ', line):
        return f"{_BLD}{_H3_FG}{_inline_md(line[4:])}{_R}"
    # H4+ (treat as bold)
    if re.match(r'^#{4,} ', line):
        content = re.sub(r'^#{4,} ', '', line)
        return f"{_BLD}{_inline_md(content)}{_R}"
    # Horizontal rule  ---  ***  ___
    if re.match(r'^[-*_]{3,}\s*$', line):
        w = shutil.get_terminal_size((80, 24)).columns - 4
        return f"{_DIM}{'─' * w}{_R}"
    # Blockquote  > text
    if line.startswith('> '):
        return f"{_DIM}│ {_inline_md(line[2:])}{_R}"
    # Unordered bullet  - / * / +
    m = re.match(r'^(\s*)([-*+]) (.+)$', line)
    if m:
        indent, _, content = m.groups()
        return f"{indent}{_DIM}•{_R} {_inline_md(content)}"
    # Ordered list  1. text
    m = re.match(r'^(\s*)(\d+)\. (.+)$', line)
    if m:
        indent, num, content = m.groups()
        return f"{indent}{_DIM}{num}.{_R} {_inline_md(content)}"
    # Regular line — inline transforms only
    return _inline_md(line)


def _md_render_chunk(text: str) -> str:
    """Render a streaming chunk: apply full markdown to complete lines,
    inline-only to the partial last line (no trailing newline)."""
    if '\n' not in text:
        return _inline_md(text)
    parts = text.split('\n')
    out = [_render_md_line(ln) for ln in parts[:-1]]
    out.append(_inline_md(parts[-1]))   # partial line — inline only
    return '\n'.join(out)


def _truncate_cmd(s: str, max_len: int = 120) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[:max_len - 1] + "…"


def _p(s: str = "", end: str = "\n") -> None:
    """Print ANSI text via prompt_toolkit — safe inside patch_stdout on all platforms."""
    print_formatted_text(ANSI(s + end), end="")


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
    """Extract the quoted payload from a shell `printf "..."` art file."""
    stripped = source.replace("\ufeff", "").strip()
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
                    codes: list[str] = []
                    if fg is not None:
                        codes.append(f"38;2;{fg[0]};{fg[1]};{fg[2]}")
                    if bg is not None:
                        codes.append(f"48;2;{bg[0]};{bg[1]};{bg[2]}")
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
            price = (
                f"${inp:.2f}/${out:.2f}"
                if inp is not None and out is not None
                else ""
            )
            current = "current" if model_id == self._current_model else ""
            meta = "  ".join(
                part for part in (provider, family, ctx_str, price, current) if part
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
        # Code block tracking for syntax highlighting
        self._in_code_block = False
        self._code_block_lang: Optional[str] = None
        self._code_block_content = ""
        # Word-wrap buffer for streaming text
        self._wrap_buffer = ""
        self._wrap_column = 0
        # Frame-rate limiting: batch text deltas arriving within 16ms (≈60 fps)
        self._stream_flush_buf: str = ""
        self._stream_last_flush: float = 0.0
        self._tool_call_inputs: dict[str, dict] = {}

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

    # ── Header — Claude Code-style welcome panel ──────────────────────────────

    def _print_header(self) -> None:
        """Print the welcome header directly to sys.__stdout__ before patch_stdout."""
        bob_version = "0.1.0"
        try:
            from bob import __version__
            bob_version = __version__
        except Exception:
            bob_version = "0.1.0"

        term_size = shutil.get_terminal_size((120, 24))
        term_w = term_size.columns
        term_h = term_size.lines
        inner_w = term_w - 4 # excluding the very outer frame chars (│  │)

        # ANSI helpers
        RST   = "\033[0m"
        DIM   = "\033[2m"
        BOLD  = "\033[1m"

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

        info_rows = [
            f"  {BOLD}System Info{RST}",
            f"  {DIM}Model:    {model}{RST}",
            f"  {DIM}Workspace: {sandbox}{RST}",
            f"  {DIM}System:    Bob v2{RST}",
            f"  {DIM}Directory: {cwd_str}{RST}",
        ]

        right_rows = self._recent_session_rows(DIM, BOLD, RST)
        right_rows.extend([
            "",
            f"  {BOLD}Quick Commands{RST}",
            f"  {DIM}• /help   - View all commands{RST}",
            f"  {DIM}• /resume - Continue last session{RST}",
            f"  {DIM}• /new    - Start fresh session{RST}",
        ])

        left_rows = [""] + info_rows + [""]
        right_rows = right_rows
        LEFT_W = max(vlen(row) for row in left_rows)
        RIGHT_W = max(vlen(row) for row in right_rows)
        min_center_w = 24
        if inner_w < LEFT_W + RIGHT_W + min_center_w + 6:
            stack_width = max(24, min(50, inner_w))
            stack_height = max(14, min(26, term_h - len(info_rows) - len(right_rows) - 8))
            character_lines, welcome_line = self._build_header_character(stack_width, stack_height)
            body_rows = [center(welcome_line, inner_w), ""]
            if character_lines:
                body_rows.extend(center(row, inner_w) for row in character_lines)
                body_rows.append("")
            body_rows.extend(info_rows)
            body_rows.append("")
            body_rows.extend(right_rows)

            title  = f"bob v{bob_version}"
            ndash  = max(0, term_w - 5 - len(title) - 2)
            top    = f"╭─── {title} {'─' * ndash}╮"
            bot    = "╰" + "─" * (term_w - 2) + "╯"

            import sys
            out = sys.__stdout__
            out.write("\n" + top + "\n")
            for row in body_rows:
                out.write(f"│ {rpad(row, inner_w)} │\n")
            out.write(bot + "\n\n")
            out.flush()
            return

        CENTER_W = inner_w - LEFT_W - RIGHT_W - 6
        art_target_width = min(max(20, CENTER_W), 52)
        center_height_budget = max(14, min(26, term_h - 8))
        character_lines, welcome_line = self._build_header_character(art_target_width, center_height_budget)

        center_rows = [center(welcome_line, CENTER_W), ""]
        if character_lines:
            center_rows.extend(center(row, CENTER_W) for row in character_lines)

        row_count = max(len(left_rows), len(center_rows), len(right_rows))
        while len(left_rows) < row_count:
            left_rows.append("")
        while len(center_rows) < row_count:
            center_rows.append("")
        while len(right_rows) < row_count:
            right_rows.append("")

        title  = f"bob v{bob_version}"
        ndash  = max(0, term_w - 5 - len(title) - 2)
        top    = f"╭─── {title} {'─' * ndash}╮"
        bot    = "╰" + "─" * (term_w - 2) + "╯"

        import sys
        out = sys.__stdout__
        out.write("\n" + top + "\n")

        for left, center_row, right in zip(left_rows, center_rows, right_rows):
            out.write(f"│ {rpad(left, LEFT_W)}   {rpad(center_row, CENTER_W)}   {rpad(right, RIGHT_W)} │\n")

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
        if "\n" not in self._stream_flush_buf:
            return
        last_newline = self._stream_flush_buf.rfind("\n")
        ready = self._stream_flush_buf[: last_newline + 1]
        self._stream_flush_buf = self._stream_flush_buf[last_newline + 1 :]
        if ready:
            _p(_md_render_chunk(ready), end="")



    async def _consume_events(self) -> None:  # noqa: C901
        from bob.protocol.events import (
            BackgroundTerminalOutputEvent,
            ErrorEvent,
            ExecApprovalRequestedEvent,
            ExecCompletedEvent,
            ExecOutputEvent,
            ExecStartedEvent,
            InfoEvent,
            NetworkApprovalRequestedEvent,
            PatchApprovalRequestedEvent,
            PlanApprovalRequestedEvent,
            PlanApprovedEvent,
            PlanRejectedEvent,
            ReasoningDeltaEvent,
            SessionEndedEvent,
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
                # ── Turn lifecycle ────────────────────────────────────────────

                if isinstance(msg, TurnStartedEvent):
                    self._task_running = True
                    self._turn_started.set()   # unblocks ❯ prompt immediately
                    self._current_buf  = ""
                    self._text_started = False
                    self._after_tool   = False
                    self._wrap_buffer = ""
                    self._wrap_column = 0
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
                                    _p(line)  # Print the opening marker
                                else:
                                    # Ending a code block - render with syntax highlighting
                                    self._in_code_block = False
                                    if self._code_block_content:
                                        from rich.console import Console
                                        from rich.syntax import Syntax
                                        import io
                                        
                                        string_io = io.StringIO()
                                        console = Console(file=string_io, force_terminal=True, width=shutil.get_terminal_size((120, 24)).columns)
                                        
                                        syntax = Syntax(
                                            self._code_block_content,
                                            self._code_block_lang or "text",
                                            theme="monokai",
                                            line_numbers=False,
                                            word_wrap=True
                                        )
                                        console.print(syntax)
                                        
                                        output = string_io.getvalue()
                                        for out_line in output.splitlines():
                                            _p(out_line)
                                    
                                    _p(line)  # Print the closing marker
                                    self._code_block_content = ""
                                    self._code_block_lang = None
                            elif self._in_code_block:
                                # Accumulate code block content
                                self._code_block_content += line + "\n"
                            else:
                                # Regular text outside code blocks — buffered
                                self._stream_flush_buf += line
                    elif self._in_code_block:
                        # Inside code block, accumulate
                        self._code_block_content += delta
                    else:
                        # Regular streaming text — buffered for frame-rate limiting
                        self._stream_flush_buf += delta

                    # Flush buffer if ≥16ms have elapsed since last render (≈60fps)
                    import time as _time
                    _now = _time.monotonic()
                    if (
                        self._stream_flush_buf
                        and "\n" in self._stream_flush_buf
                        and (_now - self._stream_last_flush) >= 0.016
                    ):
                        self._flush_completed_stream_lines()
                        self._stream_last_flush = _now
                        await asyncio.sleep(0)  # yield to event loop between batches

                # ── Tool call lifecycle ───────────────────────────────────────

                elif isinstance(msg, ToolCallStartedEvent):
                    if self._wrap_buffer:
                        self._stream_flush_buf += self._flush_wrap_buffer()
                    # Flush any buffered streaming text before tool output
                    if self._stream_flush_buf:
                        self._flush_completed_stream_lines()
                        if self._stream_flush_buf:
                            _p(_render_md_line(self._stream_flush_buf), end="")
                        self._stream_flush_buf = ""
                    # Update spinner to show which tool is running
                    tool_name = msg.tool_name
                    # Format tool name nicely (e.g., read_file -> "read file")
                    display_name = tool_name.replace("_", " ").title()
                    _NET_TOOLS = {"web_search", "web_fetch"}
                    if tool_name in _NET_TOOLS:
                        verb = "Searching…" if tool_name == "web_search" else "Fetching…"
                        self._spinner_label = f"🌐 {verb}"
                    else:
                        self._spinner_label = f"Running {display_name}…"
                    self._tool_call_inputs[msg.tool_call_id] = msg.tool_input
                    if not self._spinner_active:
                        await self._start_spinner()

                elif isinstance(msg, ToolCallCompletedEvent):
                    # Reset spinner label back to default
                    self._spinner_label = "Thinking…"
                    # Surface tool errors with file:line highlighting
                    tool_input = self._tool_call_inputs.pop(msg.tool_call_id, None)
                    if getattr(msg, 'error', None):
                        _render_error(
                            msg.error,
                            tool_name=getattr(msg, 'tool_name', None),
                            tool_input=tool_input,
                        )
                    elif isinstance(getattr(msg, "output", None), str) and msg.output.startswith("Error:"):
                        _render_error(
                            msg.output,
                            tool_name=getattr(msg, 'tool_name', None),
                            tool_input=tool_input,
                        )

                # ── Extended thinking ─────────────────────────────────────────

                elif isinstance(msg, ReasoningDeltaEvent):
                    if self._wrap_buffer:
                        self._stream_flush_buf += self._flush_wrap_buffer()
                    if self._stream_flush_buf:
                        self._flush_completed_stream_lines()
                        if self._stream_flush_buf:
                            _p(_render_md_line(self._stream_flush_buf), end="")
                        self._stream_flush_buf = ""
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

                # ── Approval — network ───────────────────────────────────────

                elif isinstance(msg, NetworkApprovalRequestedEvent):
                    await self._stop_spinner()
                    if not self._task_running:
                        self._task_running = True
                    _p()
                    _p(f"  {_y('🌐')} {_bold('Network access requested')}")
                    _p(f"     {_d('tool:')}   {msg.tool_name or 'web'}")
                    _p(f"     {_d('domain:')} {msg.domain}")
                    _p(f"     {_d('url:')}    {msg.url[:80]}")
                    _p()
                    _p(f"  {_d('[y]')} allow once  {_d('[a]')} allow always (this session)  {_d('[n]')} deny › ", end="")
                    ps_net = PromptSession()
                    try:
                        answer = (await ps_net.prompt_async("")).strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        answer = "n"
                    approved = answer in ("y", "yes", "a", "always")
                    approve_always = answer in ("a", "always")
                    if approve_always:
                        _p(f"  {_d(f'✓ {msg.domain} approved for this session')}")
                    elif approved:
                        _p(f"  {_d(f'✓ {msg.domain} allowed once')}")
                    else:
                        _p(f"  {_r(f'✗ {msg.domain} denied')}")
                    from bob.protocol.ops import NetworkApprovalOp
                    await self._session.submit(NetworkApprovalOp(
                        url=msg.url,
                        domain=msg.domain,
                        approved=approved,
                        approve_always=approve_always,
                        request_id=msg.request_id,
                        granted=approved,
                    ))

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
                    if self._wrap_buffer:
                        self._stream_flush_buf += self._flush_wrap_buffer()
                    # Flush any remaining buffered stream text — full line render
                    if self._stream_flush_buf:
                        _p(_render_md_line(self._stream_flush_buf), end="")
                        self._stream_flush_buf = ""
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
                    self._wrap_buffer = ""
                    self._wrap_column = 0
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

                    # Run post_turn hooks and surface their stdout as a status line
                    if self._config.hooks:
                        try:
                            from bob.hooks.runner import HookRunner, HookConfig as RunnerHookConfig
                            from bob.protocol.config_types import HookEventName
                            runner_hooks = []
                            for h in self._config.hooks:
                                if getattr(h, 'event', '') == HookEventName.POST_TURN:
                                    cmd = h.command.split() if isinstance(h.command, str) else [h.command]
                                    runner_hooks.append(RunnerHookConfig(
                                        event=HookEventName.POST_TURN,
                                        command=cmd,
                                        mode="sync",
                                        timeout_seconds=getattr(h, 'timeout_seconds', 10),
                                    ))
                            if runner_hooks:
                                hook_runner = HookRunner(runner_hooks)
                                results = await hook_runner.run_hooks(HookEventName.POST_TURN)
                                for r in results:
                                    if r.stdout.strip():
                                        _p(f"  {_d(r.stdout.strip())}")
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
                    _render_error(msg.message)
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
                ("Agent",       [SlashCommand.PLAN, SlashCommand.AGENT, SlashCommand.SUBAGENTS,
                                  SlashCommand.MCP, SlashCommand.HOOKS]),
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

    async def _load_model_picker_models(self) -> list[dict]:
        """Return model metadata for the interactive picker."""
        from bob.llm.catalog import get_catalog

        catalog = get_catalog()
        if catalog.is_populated():
            return catalog.list_models(status="active")

        try:
            listed = await self._session.client.list_models()
        except Exception:
            listed = []

        return [{"model_id": model_id} for model_id in listed]

    def _apply_selected_model(self, model_name: str) -> None:
        """Keep the visible config and session runtime model in sync."""
        self._config = self._config.model_copy(update={"model": model_name})
        self._session.config = self._session.config.model_copy(update={"model": model_name})
        self._session.client = self._session._make_client(model_name)

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
                event_task.cancel()
                try:
                    await event_task
                except asyncio.CancelledError:
                    pass


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_interface(session, config: BobConfig) -> None:
    """Called from bob/cli/main.py after BobSession is started."""
    await Interface(session=session, config=config).run()
