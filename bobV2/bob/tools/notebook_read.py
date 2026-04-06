from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NOTEBOOK_READ_DESCRIPTION = (
    "Read a Jupyter notebook (.ipynb) and return its cells as formatted text. "
    "Shows cell type, source code, and optional outputs."
)

NOTEBOOK_READ_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the .ipynb notebook file.",
        },
        "include_outputs": {
            "type": "boolean",
            "description": "Include cell outputs in the result (default: true).",
        },
    },
    "required": ["path"],
}

MAX_OUTPUT_CHARS = 500


async def notebook_read_handler(tool_input: dict, context: Any) -> str:
    path_str: str = tool_input.get("path", "")
    if not path_str:
        return "Error: path is required"

    include_outputs: bool = tool_input.get("include_outputs", True)

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
    if not cells:
        return "(notebook has no cells)"

    parts: list[str] = [f"# Notebook: {p.name} ({len(cells)} cells)\n"]

    for i, cell in enumerate(cells):
        cell_type = cell.get("cell_type", "unknown")
        source = "".join(cell.get("source", []))
        parts.append(f"## Cell {i + 1} [{cell_type}]")
        parts.append(source)

        if include_outputs and cell_type == "code":
            outputs = cell.get("outputs", [])
            if outputs:
                out_lines: list[str] = []
                for output in outputs:
                    otype = output.get("output_type", "")
                    if otype in ("stream", "display_data", "execute_result"):
                        text = output.get("text") or output.get("data", {}).get("text/plain", [])
                        if isinstance(text, list):
                            text = "".join(text)
                        if text:
                            out_lines.append(str(text))
                if out_lines:
                    combined = "\n".join(out_lines)
                    if len(combined) > MAX_OUTPUT_CHARS:
                        combined = combined[:MAX_OUTPUT_CHARS] + f"\n[...truncated]"
                    parts.append(f"**Output:**\n```\n{combined}\n```")

        parts.append("")

    return "\n".join(parts)
