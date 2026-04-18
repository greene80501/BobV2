from __future__ import annotations

import html
import os
import re
import urllib.parse
import urllib.request
from typing import Any

WEB_SEARCH_DESCRIPTION = (
    "Search the web using DuckDuckGo. Use this tool FIRST when the user asks you to "
    "look something up, research a topic, or find documentation - before attempting "
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


def _normalize_results(rows: list[dict], max_results: int) -> list[dict]:
    normalized: list[dict] = []
    for row in rows[:max_results]:
        normalized.append({
            "title": row.get("title", "Untitled"),
            "href": row.get("href", ""),
            "body": row.get("body", ""),
        })
    return normalized


def _search_ddg(query: str, max_results: int) -> tuple[list[dict], str | None]:
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return [], "ddgs is not installed. Run: pip install ddgs"

    results: list[dict] = []
    ddg_error: str | None = None
    try:
        with DDGS() as ddgs:
            for row in ddgs.text(query, max_results=max_results):
                results.append(row)
    except Exception as exc:
        ddg_error = str(exc)
    return _normalize_results(results, max_results), ddg_error


def _get_proxy(context: Any) -> str:
    session = getattr(context, "_session", None)
    return getattr(getattr(session, "config", None), "network_proxy", "") or ""


def _search_brave(query: str, max_results: int, api_key: str, proxy: str = "") -> tuple[list[dict], str | None]:
    try:
        import requests
        proxy_kwargs = {"proxies": {"http": proxy, "https": proxy}} if proxy else {}
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
            timeout=10,
            **proxy_kwargs,
        )
        resp.raise_for_status()
        data = resp.json()
        rows = []
        for row in (data.get("web", {}) or {}).get("results", [])[:max_results]:
            rows.append({
                "title": row.get("title", "Untitled"),
                "href": row.get("url", ""),
                "body": row.get("description", ""),
            })
        return rows, None
    except Exception as exc:
        return [], str(exc)


def _search_serpapi(query: str, max_results: int, api_key: str, proxy: str = "") -> tuple[list[dict], str | None]:
    try:
        import requests
        proxy_kwargs = {"proxies": {"http": proxy, "https": proxy}} if proxy else {}
        resp = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google",
                "q": query,
                "api_key": api_key,
                "num": max_results,
            },
            timeout=10,
            **proxy_kwargs,
        )
        resp.raise_for_status()
        data = resp.json()
        rows = []
        for row in data.get("organic_results", [])[:max_results]:
            rows.append({
                "title": row.get("title", "Untitled"),
                "href": row.get("link", ""),
                "body": row.get("snippet", ""),
            })
        return rows, None
    except Exception as exc:
        return [], str(exc)


def _search_ddg_html(query: str, max_results: int) -> tuple[list[dict], str | None]:
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        titles = re.findall(r'class="result__title"[^>]*>.*?<a[^>]*>(.*?)</a>', body, re.S)
        urls = re.findall(r'class="result__url"[^>]*>(.*?)<', body, re.S)
        snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', body, re.S)
        rows = []
        for i in range(min(max_results, len(titles))):
            rows.append({
                "title": html.unescape(re.sub(r"<[^>]+>", "", titles[i])).strip(),
                "href": html.unescape(urls[i].strip()) if i < len(urls) else "",
                "body": html.unescape(re.sub(r"<[^>]+>", "", snips[i])).strip() if i < len(snips) else "",
            })
        return rows, None
    except Exception as exc:
        return [], str(exc)


def _fallback_provider_attempts(query: str, max_results: int, context: Any) -> tuple[list[dict], list[str]]:
    session = getattr(context, "_session", None)
    extra = getattr(getattr(session, "config", None), "extra", {}) or {}
    proxy = _get_proxy(context)

    brave_key = (
        extra.get("brave_search_api_key")
        or os.environ.get("BRAVE_SEARCH_API_KEY")
        or os.environ.get("BRAVE_API_KEY")
        or ""
    )
    serp_key = (
        extra.get("serpapi_api_key")
        or os.environ.get("SERPAPI_API_KEY")
        or os.environ.get("SERPAPI_KEY")
        or ""
    )

    errors: list[str] = []
    if brave_key:
        results, err = _search_brave(query, max_results, brave_key, proxy=proxy)
        if results:
            return results, ["Brave Search fallback"]
        if err:
            errors.append(f"Brave Search fallback failed: {err}")

    if serp_key:
        results, err = _search_serpapi(query, max_results, serp_key, proxy=proxy)
        if results:
            return results, ["SerpAPI fallback"]
        if err:
            errors.append(f"SerpAPI fallback failed: {err}")

    results, err = _search_ddg_html(query, max_results)
    if results:
        return results, ["DuckDuckGo HTML fallback"]
    if err:
        errors.append(f"DuckDuckGo HTML fallback failed: {err}")
    return [], errors


async def web_search_handler(tool_input: dict, context: Any) -> str:
    query: str = tool_input.get("query", "")
    if not query:
        return "Error: query is required"

    max_results: int = tool_input.get("max_results", 5)
    results, ddg_error = _search_ddg(query, max_results)
    source_notes: list[str] = []
    if results:
        source_notes.append("DuckDuckGo")

    if not results:
        fallback_results, fallback_notes = _fallback_provider_attempts(query, max_results, context)
        results = fallback_results
        source_notes.extend(fallback_notes)

    if not results:
        msg = f"No results found for: {query}"
        if ddg_error:
            msg += f" (DDG error: {ddg_error})"
        if source_notes:
            msg += f" [{' | '.join(source_notes)}]"
        return msg

    lines: list[str] = [f"## Search results for: {query}\n"]
    if source_notes:
        lines.append(f"_Source: {', '.join(source_notes)}_\n")
    for i, row in enumerate(results, 1):
        title = row.get("title", "Untitled")
        url = row.get("href", "")
        body = row.get("body", "")
        lines.append(f"### {i}. {title}")
        if url:
            lines.append(f"**URL**: {url}")
        if body:
            lines.append(f"\n{body}\n")

    return "\n".join(lines)
