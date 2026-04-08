from __future__ import annotations

from typing import Any

WEB_SEARCH_DESCRIPTION = (
    "Search the web using DuckDuckGo. Use this tool FIRST when the user asks you to "
    "look something up, research a topic, or find documentation — before attempting "
    "web_fetch. Returns title, URL, and snippet for each result."
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
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return "Error: ddgs is not installed. Run: pip install ddgs"

    results = []
    ddg_error: str | None = None
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(r)
    except Exception as exc:
        ddg_error = str(exc)

    # Fallback: try the DuckDuckGo HTML endpoint directly when the API fails
    if not results and ddg_error:
        try:
            import urllib.request
            import urllib.parse
            import html
            import re as _re
            encoded = urllib.parse.quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            # Parse result snippets from HTML
            titles = _re.findall(r'class="result__title"[^>]*>.*?<a[^>]*>(.*?)</a>', body, _re.S)
            urls   = _re.findall(r'class="result__url"[^>]*>(.*?)<', body, _re.S)
            snips  = _re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', body, _re.S)
            for i in range(min(max_results, len(titles))):
                results.append({
                    "title": html.unescape(_re.sub(r"<[^>]+>", "", titles[i])).strip(),
                    "href":  html.unescape(urls[i].strip()) if i < len(urls) else "",
                    "body":  html.unescape(_re.sub(r"<[^>]+>", "", snips[i])).strip() if i < len(snips) else "",
                })
        except Exception:
            pass  # Both DDG methods failed; fall through to "no results"

    if not results:
        msg = f"No results found for: {query}"
        if ddg_error:
            msg += f" (DDG error: {ddg_error})"
        return msg

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
