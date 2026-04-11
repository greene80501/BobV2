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


def resolve_tool_path(path_value: str, cwd: Path) -> Path:
    raw = normalize_tool_path(path_value)
    p = Path(raw)
    if not p.is_absolute():
        p = cwd / p
    return p.resolve()

