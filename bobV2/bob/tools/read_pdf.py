from __future__ import annotations

from pathlib import Path
from typing import Any
from bob.tools.path_utils import resolve_tool_path

READ_PDF_DESCRIPTION = (
    "Read text content from a PDF file. "
    "Supports page-range selection (e.g. pages='1-5' or pages='3'). "
    "Pages are 1-indexed. Returns extracted text with page markers. "
    "Use read_file for plain text; use this tool only for .pdf files."
)

READ_PDF_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the PDF file (relative to cwd or absolute).",
        },
        "pages": {
            "type": "string",
            "description": (
                "Page range to extract, e.g. '1-5' or '3'. "
                "Defaults to all pages (capped at 50)."
            ),
        },
        "max_chars_per_page": {
            "type": "integer",
            "description": "Maximum characters to return per page. Default: 4000.",
        },
    },
    "required": ["path"],
}

_MAX_PAGES_DEFAULT = 50
_MAX_CHARS_PER_PAGE = 4_000


def _parse_page_range(spec: str, total: int) -> tuple[int, int]:
    """Parse '1-5' or '3' into 0-based (start, end_exclusive)."""
    spec = spec.strip()
    if "-" in spec:
        parts = spec.split("-", 1)
        start = max(1, int(parts[0].strip()))
        end = min(total, int(parts[1].strip()))
    else:
        page = max(1, min(total, int(spec)))
        start = end = page
    return start - 1, end  # convert to 0-based [start, end)


async def read_pdf_handler(tool_input: dict, context: Any) -> str:
    path_str: str = tool_input.get("path", "")
    if not path_str:
        return "Error: path is required"

    p = resolve_tool_path(path_str, context.cwd)

    if not p.exists():
        return f"Error: file not found: {p}"
    if not p.is_file():
        return f"Error: not a file: {p}"
    if p.suffix.lower() != ".pdf":
        return f"Error: not a PDF file: {p} (use read_file for non-PDF files)"

    try:
        from pypdf import PdfReader
    except ImportError:
        return (
            "Error: pypdf is not installed. "
            "Install it with: pip install pypdf"
        )

    max_chars = int(tool_input.get("max_chars_per_page", _MAX_CHARS_PER_PAGE))

    try:
        reader = PdfReader(str(p))
    except Exception as exc:
        return f"Error opening PDF {p}: {exc}"

    total_pages = len(reader.pages)
    if total_pages == 0:
        return f"PDF has no pages: {p}"

    pages_spec = tool_input.get("pages", "")
    if pages_spec:
        try:
            start_idx, end_idx = _parse_page_range(str(pages_spec), total_pages)
        except (ValueError, TypeError):
            return f"Error: invalid pages spec '{pages_spec}' — use '1-5' or '3'"
    else:
        start_idx = 0
        end_idx = min(total_pages, _MAX_PAGES_DEFAULT)

    # Safety cap
    if end_idx - start_idx > _MAX_PAGES_DEFAULT:
        end_idx = start_idx + _MAX_PAGES_DEFAULT

    parts: list[str] = [f"PDF: {p.name} ({total_pages} pages total)\n"]

    for page_num in range(start_idx, end_idx):
        try:
            page = reader.pages[page_num]
            text = page.extract_text() or ""
        except Exception as exc:
            text = f"[extraction error: {exc}]"

        text = text.strip()
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n[...truncated at {max_chars} chars]"

        parts.append(f"--- Page {page_num + 1} ---\n{text or '(no extractable text)'}")

    shown = end_idx - start_idx
    if shown < total_pages:
        parts.append(
            f"\n[Showing pages {start_idx + 1}–{end_idx} of {total_pages}. "
            f"Use pages='N-M' to read other pages.]"
        )

    return "\n\n".join(parts)
