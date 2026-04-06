from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Hunk:
    """A single @@ hunk inside an update operation."""

    header: str = ""
    lines: list[tuple[str, str]] = field(default_factory=list)
    # Each entry is (op, text) where op is " " (context), "+" (add), or "-" (remove).


@dataclass
class FileOp:
    """A single file operation parsed from a patch."""

    op: str  # "add" | "update" | "delete"
    path: str
    move_to: Optional[str] = None
    new_content_lines: list[str] = field(default_factory=list)  # for "add"
    hunks: list[Hunk] = field(default_factory=list)             # for "update"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_patch(patch_text: str) -> list[FileOp]:
    """
    Parse the custom bob patch format into a list of :class:`FileOp` objects.

    Format example::

        *** Begin Patch
        *** Add File: src/foo.py
        +def hello():
        +    pass
        *** Update File: src/bar.py
        @@ replace greeting
         def greet():
        -    return "Hi"
        +    return "Hello"
        *** Delete File: src/old.py
        *** End Patch
    """
    lines = patch_text.splitlines()
    ops: list[FileOp] = []
    current_op: Optional[FileOp] = None
    current_hunk: Optional[Hunk] = None
    in_patch = False

    def _flush_hunk() -> None:
        nonlocal current_hunk
        if current_hunk is not None and current_op is not None:
            current_op.hunks.append(current_hunk)
            current_hunk = None

    def _flush_op() -> None:
        _flush_hunk()
        if current_op is not None:
            ops.append(current_op)

    for line in lines:
        if line == "*** Begin Patch":
            in_patch = True
            continue

        if line == "*** End Patch":
            _flush_op()
            break

        if not in_patch:
            continue

        # --- Operation headers --------------------------------------------
        if line.startswith("*** Add File: "):
            _flush_op()
            current_op = FileOp(op="add", path=line[len("*** Add File: "):])
            current_hunk = None

        elif line.startswith("*** Delete File: "):
            _flush_op()
            current_op = FileOp(op="delete", path=line[len("*** Delete File: "):])
            current_hunk = None

        elif line.startswith("*** Update File: "):
            _flush_op()
            current_op = FileOp(op="update", path=line[len("*** Update File: "):])
            current_hunk = None

        elif line.startswith("*** Move to: ") and current_op is not None:
            current_op.move_to = line[len("*** Move to: "):]

        # --- Hunk header --------------------------------------------------
        elif line.startswith("@@") and current_op is not None and current_op.op == "update":
            _flush_hunk()
            current_hunk = Hunk(header=line[2:].strip())

        # --- Content lines ------------------------------------------------
        elif current_op is not None and current_op.op == "add":
            # "add" file content: lines prefixed with "+"
            if line.startswith("+"):
                current_op.new_content_lines.append(line[1:])

        elif (
            current_op is not None
            and current_op.op == "update"
            and current_hunk is not None
        ):
            if line.startswith((" ", "+", "-")):
                current_hunk.lines.append((line[0], line[1:]))
            elif line == "*** End of File":
                pass  # marker only; no content

    return ops


# ---------------------------------------------------------------------------
# Hunk applier
# ---------------------------------------------------------------------------


def apply_hunk(content_lines: list[str], hunk: Hunk) -> list[str]:
    """
    Apply *hunk* to *content_lines* and return the updated line list.

    The algorithm locates the first occurrence of the context+removal lines
    in *content_lines*, then replaces/augments them in-place.  If the context
    cannot be located (e.g. file already partially patched), the additions
    from the hunk are appended at the end of the file as a safe fallback.
    """
    if not hunk.lines:
        return list(content_lines)

    # Build the sequence of lines we must find: context (" ") + removed ("-")
    pattern: list[str] = [
        text for op, text in hunk.lines if op in (" ", "-")
    ]

    # Normalise line endings for matching
    def _norm(s: str) -> str:
        return s.rstrip("\r\n")

    norm_pattern = [_norm(p) for p in pattern]
    norm_content = [_norm(c) for c in content_lines]

    start_idx: Optional[int] = None
    if norm_pattern:
        for i in range(len(norm_content) - len(norm_pattern) + 1):
            if norm_content[i : i + len(norm_pattern)] == norm_pattern:
                start_idx = i
                break
    else:
        start_idx = 0  # nothing to match; apply at beginning

    if start_idx is None:
        # Context not found — append additions as a best-effort fallback
        new_lines = list(content_lines)
        for op, text in hunk.lines:
            if op == "+":
                new_lines.append(text + "\n" if not text.endswith("\n") else text)
        return new_lines

    # Rebuild lines around the matched region
    new_lines: list[str] = list(content_lines[:start_idx])
    pattern_idx = start_idx  # pointer into original content

    for op, text in hunk.lines:
        if op == " ":
            # Keep original line (preserves original line ending)
            new_lines.append(content_lines[pattern_idx])
            pattern_idx += 1
        elif op == "-":
            # Skip original line
            pattern_idx += 1
        elif op == "+":
            # Insert new line
            line = text if text.endswith("\n") else text + "\n"
            new_lines.append(line)

    # Append remaining lines after the matched region
    new_lines.extend(content_lines[pattern_idx:])
    return new_lines


# ---------------------------------------------------------------------------
# Top-level command entry point
# ---------------------------------------------------------------------------


async def apply_patch_command(patch_text: str, cwd: Path) -> str:
    """
    Parse *patch_text* and apply all file operations relative to *cwd*.

    Returns a human-readable result string summarising what was done,
    or an error message if parsing or any operation fails.
    """
    try:
        ops = parse_patch(patch_text)
    except Exception as exc:
        return f"Error parsing patch: {exc}"

    if not ops:
        return "Error: no file operations found in patch"

    results: list[str] = []

    for op in ops:
        path = (cwd / op.path).resolve()
        try:
            if op.op == "add":
                path.parent.mkdir(parents=True, exist_ok=True)
                content = "\n".join(op.new_content_lines)
                if content and not content.endswith("\n"):
                    content += "\n"
                path.write_text(content, encoding="utf-8")
                results.append(f"Added: {op.path}")

            elif op.op == "delete":
                if path.exists():
                    path.unlink()
                    results.append(f"Deleted: {op.path}")
                else:
                    results.append(f"Warning: {op.path} not found (already deleted?)")

            elif op.op == "update":
                if not path.exists():
                    results.append(f"Error: file not found for update: {op.path}")
                    continue

                raw = path.read_text(encoding="utf-8", errors="replace")
                content_lines = raw.splitlines(keepends=True)

                for hunk in op.hunks:
                    content_lines = apply_hunk(content_lines, hunk)

                new_content = "".join(content_lines)

                if op.move_to:
                    dest = (cwd / op.move_to).resolve()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(new_content, encoding="utf-8")
                    path.unlink()
                    results.append(f"Updated and moved: {op.path} -> {op.move_to}")
                else:
                    path.write_text(new_content, encoding="utf-8")
                    results.append(f"Updated: {op.path}")

        except Exception as exc:
            results.append(f"Error with {op.path}: {exc}")

    return "\n".join(results) if results else "Patch applied (no changes)"
