from __future__ import annotations

import asyncio
import html
import os
import re
import urllib.parse
import urllib.request
from typing import Any

WEB_SEARCH_DESCRIPTION = (
    "Search the web for discovery and research. Supports single-query and multi-query runs, "
    "returns titles/URLs/snippets, and can optionally fetch the top result pages for deeper ingestion. "
    "Use this tool first when the user asks for research, current information, or documentation."
)

WEB_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Single search query.",
        },
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional list of queries to run in one request.",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum results per query (default from config, cap from config).",
        },
        "fetch_pages": {
            "type": "boolean",
            "description": "When true, fetch the body content of top result pages for deeper ingestion.",
        },
        "fetch_per_query": {
            "type": "integer",
            "description": "How many result pages to fetch per query when fetch_pages=true.",
        },
        "max_concurrency": {
            "type": "integer",
            "description": "Maximum concurrent search/fetch requests for this call.",
        },
        "allowed_domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional domain allowlist for result filtering.",
        },
        "providers": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional provider order. Supported: ddg, brave, serpapi, ddg_html.",
        },
    },
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


def _provider_keys(context: Any) -> tuple[str, str]:
    session = getattr(context, "_session", None)
    extra = getattr(getattr(session, "config", None), "extra", {}) or {}
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
    return brave_key, serp_key


def _provider_search(
    provider: str,
    query: str,
    max_results: int,
    *,
    brave_key: str,
    serp_key: str,
    proxy: str,
) -> tuple[list[dict], str | None]:
    if provider == "ddg":
        return _search_ddg(query, max_results)
    if provider == "brave":
        if not brave_key:
            return [], "Brave Search API key is not configured"
        return _search_brave(query, max_results, brave_key, proxy=proxy)
    if provider == "serpapi":
        if not serp_key:
            return [], "SerpAPI key is not configured"
        return _search_serpapi(query, max_results, serp_key, proxy=proxy)
    if provider == "ddg_html":
        return _search_ddg_html(query, max_results)
    return [], f"Unknown provider: {provider}"


def _extract_domain(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        return (parsed.netloc or parsed.path.split("/")[0]).lower()
    except Exception:
        return ""


def _domain_allowed(url: str, allowed_domains: list[str] | None) -> bool:
    if not allowed_domains:
        return True
    domain = _extract_domain(url)
    if not domain:
        return False
    for pattern in allowed_domains:
        pattern = pattern.lower()
        if pattern == domain:
            return True
        if pattern.startswith("*.") and (domain == pattern[2:] or domain.endswith(pattern[1:])):
            return True
    return False


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


async def _fetch_page_excerpt(
    client: Any,
    url: str,
    *,
    timeout_seconds: float,
    max_chars: int = 6000,
) -> str:
    try:
        response = await client.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:
        return f"[fetch error] {exc}"

    content_type = response.headers.get("content-type", "")
    text = response.text
    if "html" in content_type:
        try:
            import html2text

            parser = html2text.HTML2Text()
            parser.ignore_links = False
            parser.body_width = 0
            text = parser.handle(text)
        except ImportError:
            text = _strip_tags(text)

    text = text.strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n... [truncated]"
    return text or "(empty page)"


def _get_search_config(context: Any) -> tuple[int, int, bool, int, int, float, list[str] | None]:
    session = getattr(context, "_session", None)
    cfg = getattr(getattr(session, "config", None), "web_search", None)
    if cfg is None:
        return 10, 50, False, 3, 8, 15.0, None
    return (
        int(getattr(cfg, "default_max_results", 10) or 10),
        int(getattr(cfg, "max_results_cap", 50) or 50),
        bool(getattr(cfg, "default_fetch_pages", False)),
        int(getattr(cfg, "default_fetch_per_query", 3) or 3),
        int(getattr(cfg, "max_concurrency", 8) or 8),
        float(getattr(cfg, "fetch_timeout_seconds", 15.0) or 15.0),
        getattr(cfg, "allowed_domains", None),
    )


async def _run_single_query(
    query: str,
    *,
    max_results: int,
    providers: list[str],
    allowed_domains: list[str] | None,
    brave_key: str,
    serp_key: str,
    proxy: str,
) -> dict[str, Any]:
    errors: list[str] = []
    for provider in providers:
        results, err = await asyncio.to_thread(
            _provider_search,
            provider,
            query,
            max_results,
            brave_key=brave_key,
            serp_key=serp_key,
            proxy=proxy,
        )
        if allowed_domains:
            results = [row for row in results if _domain_allowed(str(row.get("href", "")), allowed_domains)]
        if results:
            return {
                "query": query,
                "provider": provider,
                "results": results,
                "errors": errors,
            }
        if err:
            errors.append(f"{provider}: {err}")
    return {
        "query": query,
        "provider": None,
        "results": [],
        "errors": errors,
    }


async def web_search_handler(tool_input: dict, context: Any) -> str:
    raw_query = str(tool_input.get("query", "") or "").strip()
    raw_queries = [str(q).strip() for q in (tool_input.get("queries") or []) if str(q).strip()]
    queries = raw_queries or ([raw_query] if raw_query else [])
    if not queries:
        return "Error: query or queries is required"

    cfg_default_max, cfg_cap, cfg_fetch_pages, cfg_fetch_per_query, cfg_concurrency, cfg_timeout, cfg_allowed_domains = _get_search_config(context)
    try:
        requested_max_results = int(tool_input.get("max_results", cfg_default_max))
    except (TypeError, ValueError):
        return "Error: max_results must be an integer"
    max_results = max(1, min(requested_max_results, cfg_cap))

    fetch_pages = bool(tool_input.get("fetch_pages", cfg_fetch_pages))
    try:
        fetch_per_query = int(tool_input.get("fetch_per_query", cfg_fetch_per_query))
    except (TypeError, ValueError):
        return "Error: fetch_per_query must be an integer"
    fetch_per_query = max(0, min(fetch_per_query, max_results))

    try:
        max_concurrency = int(tool_input.get("max_concurrency", cfg_concurrency))
    except (TypeError, ValueError):
        return "Error: max_concurrency must be an integer"
    max_concurrency = max(1, min(max_concurrency, 16))

    allowed_domains = [str(d).strip() for d in (tool_input.get("allowed_domains") or cfg_allowed_domains or []) if str(d).strip()] or None
    providers = [str(p).strip().lower() for p in (tool_input.get("providers") or []) if str(p).strip()]
    if not providers:
        providers = ["ddg", "brave", "serpapi", "ddg_html"]

    proxy = _get_proxy(context)
    brave_key, serp_key = _provider_keys(context)

    sem = asyncio.Semaphore(max_concurrency)

    async def _bounded_single(query: str) -> dict[str, Any]:
        async with sem:
            return await _run_single_query(
                query,
                max_results=max_results,
                providers=providers,
                allowed_domains=allowed_domains,
                brave_key=brave_key,
                serp_key=serp_key,
                proxy=proxy,
            )

    query_results = await asyncio.gather(*[_bounded_single(query) for query in queries])

    if fetch_pages:
        try:
            import httpx
        except ImportError:
            return "Error: httpx is not installed. Run: pip install httpx"

        proxy_kwargs = {"proxies": proxy} if proxy else {}
        async with httpx.AsyncClient(**proxy_kwargs) as client:
            fetch_tasks: list[tuple[dict[str, Any], dict[str, Any], asyncio.Task[str]]] = []
            seen_urls: set[str] = set()
            for qres in query_results:
                for row in qres["results"][:fetch_per_query]:
                    url = str(row.get("href", "") or "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    fetch_tasks.append((
                        qres,
                        row,
                        asyncio.create_task(
                            _fetch_page_excerpt(client, url, timeout_seconds=cfg_timeout)
                        ),
                    ))
            for qres, row, task in fetch_tasks:
                row["content"] = await task

    if not any(qres["results"] for qres in query_results):
        messages = []
        for qres in query_results:
            if qres["errors"]:
                messages.append(f"{qres['query']}: {' | '.join(qres['errors'])}")
        detail = f" ({'; '.join(messages)})" if messages else ""
        return f"No results found for: {', '.join(queries)}{detail}"

    lines: list[str] = []
    if len(queries) > 1:
        lines.append(f"# Web research results ({len(queries)} queries)")
        lines.append("")
    for qres in query_results:
        query = qres["query"]
        provider = qres["provider"] or "none"
        lines.append(f"## Search results for: {query}")
        lines.append(f"_Provider: {provider}_")
        if qres["errors"]:
            lines.append(f"_Fallback notes: {' | '.join(qres['errors'])}_")
        lines.append("")
        for i, row in enumerate(qres["results"], 1):
            title = row.get("title", "Untitled")
            url = row.get("href", "")
            body = row.get("body", "")
            lines.append(f"### {i}. {title}")
            if url:
                lines.append(f"**URL**: {url}")
            if body:
                lines.append(f"\n{body}\n")
            content = row.get("content")
            if content:
                lines.append("**Fetched content excerpt:**")
                lines.append("")
                lines.append(content)
                lines.append("")
        lines.append("")

    return "\n".join(lines).strip()
