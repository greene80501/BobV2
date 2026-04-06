from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NOTEBOOK_EDIT_DESCRIPTION = (
    "Edit a cell in a Jupyter notebook (.ipynb). "
    "Replaces the source of the specified cell (0-indexed) and optionally clears outputs."
)

NOTEBOOK_EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the .ipynb notebook file.",
        },
        "cell_index": {
            "type": "integer",
            "description": "0-based index of the cell to edit.",
        },
        "new_source": {
            "type": "string",
            "description": "New source code or text for the cell.",
        },
        "clear_outputs": {
            "type": "boolean",
            "description": "Clear the cell's outputs after editing (default: false).",
        },
    },
    "required": ["path", "cell_index", "new_source"],
}


async def notebook_edit_handler(tool_input: dict, context: Any) -> str:
    path_str: str = tool_input.get("path", "")
    if not path_str:
        return "Error: path is required"

    cell_index: int = tool_input.get("cell_index", 0)
    new_source: str = tool_input.get("new_source", "")
    clear_outputs: bool = tool_input.get("clear_outputs", False)

    p = Path(path_str)
    if not p.is_absolute():
        p = context.cwd / p

    if not p.exists():
        return f"Error: file not found: {p}"

    try:
        nb = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return f"Error reading notebook: {exc}"

    cells = nb.get("cells", [])
    if not (0 <= cell_index < len(cells)):
        return f"Error: cell_index {cell_index} is out of range (notebook has {len(cells)} cells)"

    cell = cells[cell_index]
    cell["source"] = new_source.splitlines(keepends=True)

    if clear_outputs and "outputs" in cell:
        cell["outputs"] = []
        cell["execution_count"] = None

    try:
        p.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        return f"Error writing notebook: {exc}"

    cell_type = cell.get("cell_type", "unknown")
    return f"Updated cell {cell_index} [{cell_type}] in {p.name}"
