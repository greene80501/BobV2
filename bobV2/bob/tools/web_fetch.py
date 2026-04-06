from __future__ import annotations

from typing import Any

WEB_FETCH_DESCRIPTION = (
    "Fetch the content of a URL. HTML pages are converted to Markdown. "
    "Output is truncated at max_length characters."
)

WEB_FETCH_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "URL to fetch.",
        },
        "max_length": {
            "type": "integer",
            "description": "Maximum characters to return (default: 50000).",
        },
        "start_index": {
            "type": "integer",
            "description": "Character offset for pagination (default: 0).",
        },
    },
    "required": ["url"],
}

MAX_LENGTH = 50_000


async def web_fetch_handler(tool_input: dict, context: Any) -> str:
    url: str = tool_input.get("url", "")
    if not url:
        return "Error: url is required"

    max_length: int = tool_input.get("max_length", MAX_LENGTH)
    start_index: int = tool_input.get("start_index", 0)

    try:
        import httpx
    except ImportError:
        return "Error: httpx is not installed. Run: pip install httpx"

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(url, headers={"User-Agent": "bob/1.0"})
            response.raise_for_status()
    except Exception as exc:
        return f"Error fetching {url}: {exc}"

    content_type = response.headers.get("content-type", "")
    raw = response.text

    if "html" in content_type:
        try:
            import html2text
            h = html2text.HTML2Text()
            h.ignore_links = False
            h.body_width = 0
            raw = h.handle(raw)
        except ImportError:
            # Strip tags crudely if html2text not available
            import re
            raw = re.sub(r"<[^>]+>", "", raw)

    # Paginate
    chunk = raw[start_index : start_index + max_length]
    total = len(raw)

    result = chunk
    if start_index + max_length < total:
        result += f"\n\n[...content truncated. Total: {total} chars. Use start_index={start_index + max_length} for next page.]"

    return result or "(empty response)"
