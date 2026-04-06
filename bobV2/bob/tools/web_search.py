from __future__ import annotations

from typing import Any

WEB_SEARCH_DESCRIPTION = (
    "Search the web using DuckDuckGo and return the top results as Markdown. "
    "Returns title, URL, and snippet for each result."
)

WEB_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query.",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of results to return (default: 5).",
        },
    },
    "required": ["query"],
}


async def web_search_handler(tool_input: dict, context: Any) -> str:
    query: str = tool_input.get("query", "")
    if not query:
        return "Error: query is required"

    max_results: int = tool_input.get("max_results", 5)

    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "Error: duckduckgo_search is not installed. Run: pip install duckduckgo-search"

    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(r)
    except Exception as exc:
        return f"Error searching: {exc}"

    if not results:
        return f"No results found for: {query}"

    lines: list[str] = [f"## Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "Untitled")
        url = r.get("href", "")
        body = r.get("body", "")
        lines.append(f"### {i}. {title}")
        if url:
            lines.append(f"**URL**: {url}")
        if body:
            lines.append(f"\n{body}\n")

    return "\n".join(lines)
