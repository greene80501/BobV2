from __future__ import annotations

from pathlib import Path


_CONTROL_ESCAPE_REPAIR = {
    "\b": r"\b",
    "\f": r"\f",
    "\n": r"\n",
    "\r": r"\r",
    "\t": r"\t",
}


def normalize_tool_path(value: str) -> str:
    """
    Repair JSON-escaped control chars that commonly appear in Windows paths.

    Example:
      ".\\bobV2" emitted by a model as JSON may decode to ".<backspace>obV2".
      This function repairs it back to ".\\bobV2".
    """
    if not value:
        return value
    out = value
    for ctrl, escaped in _CONTROL_ESCAPE_REPAIR.items():
        out = out.replace(ctrl, escaped)
    return out


def _strip_redundant_cwd_prefix(path: Path, cwd: Path) -> Path:
    """
    Recover from model guesses like ``bobV2/README.md`` when the current working
    directory is already ``.../bobV2``.
    """
    if path.is_absolute():
        return path

    parts = path.parts
    if not parts:
        return path

    cwd_name = cwd.name.casefold()
    if not cwd_name:
        return path

    index = 0
    while index < len(parts) and parts[index].casefold() == cwd_name:
        index += 1

    if index == 0:
        return path
    if index >= len(parts):
        return Path(".")
    return Path(*parts[index:])


def resolve_tool_path(path_value: str, cwd: Path) -> Path:
    raw = normalize_tool_path(path_value)
    p = Path(raw)
    if not p.is_absolute():
        direct = (cwd / p).resolve()
        if direct.exists():
            return direct

        repaired = _strip_redundant_cwd_prefix(p, cwd)
        p = cwd / repaired
    return p.resolve()

