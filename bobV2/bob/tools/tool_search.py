from __future__ import annotations

from typing import Any

TOOL_SEARCH_DESCRIPTION = (
    "Search discoverable tools and optionally expose matches to the model. "
    "Use this when the tool catalog is large or when app/MCP tools are hidden by default."
)

TOOL_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search text for tool name, description, or keywords.",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of results (default: 20, max: 200).",
        },
        "include_hidden": {
            "type": "boolean",
            "description": "Include hidden/deferred tools in search results (default: true).",
        },
        "sources": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional source filters such as core, mcp, app, dynamic.",
        },
        "auto_enable": {
            "type": "boolean",
            "description": "If true, expose matched hidden tools to the model.",
        },
        "select": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Explicit tool names to select directly (alternative to query).",
        },
    },
    "required": [],
}


async def tool_search_handler(tool_input: dict, context: Any) -> str:
    session = getattr(context, "_session", None)
    if session is None:
        return "Error: tool search unavailable (missing session context)"

    query = str(tool_input.get("query", "") or "")
    raw_limit = tool_input.get("limit", 20)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return "Error: limit must be an integer"

    include_hidden = bool(tool_input.get("include_hidden", True))
    auto_enable = bool(tool_input.get("auto_enable", False))
    sources = [str(x).strip() for x in (tool_input.get("sources") or []) if str(x).strip()]

    rows: list[dict[str, Any]]
    selected_names: list[str] = []
    requested = [str(x).strip() for x in (tool_input.get("select") or []) if str(x).strip()]
    if not requested and query.lower().startswith("select:"):
        requested = [part.strip() for part in query.split(":", 1)[1].split(",") if part.strip()]
    if requested:
        rows = []
        for name in requested:
            tool = session.tool_registry.get_tool(name)
            if tool is None:
                continue
            if sources and tool.source not in sources:
                continue
            if not include_hidden and not tool.expose_to_model:
                continue
            rows.append({
                "name": tool.name,
                "description": tool.description,
                "source": tool.source,
                "is_mutating": tool.is_mutating,
                "supports_parallel": tool.supports_parallel,
                "requires_network_approval": tool.requires_network_approval,
                "expose_to_model": tool.expose_to_model,
                "discoverable": tool.discoverable,
                "deferred": tool.deferred,
                "keywords": list(tool.keywords or []),
            })
        selected_names = [r["name"] for r in rows]
    else:
        rows = session.tool_registry.search_tools(
            query=query,
            limit=limit,
            include_hidden=include_hidden,
            sources=sources or None,
        )

    if not rows:
        return "No tools matched your search."

    enabled: list[str] = []
    if auto_enable:
        to_enable = [r["name"] for r in rows if not bool(r.get("expose_to_model", False))]
        enabled = session.tool_registry.enable_tools(to_enable, expose_to_model=True)
        for name in enabled:
            await session.tool_registry.ensure_tool_loaded(name)

    prefix = "Selected" if selected_names else "Found"
    lines = [f"{prefix} {len(rows)} tool(s):"]
    for row in rows:
        state = "exposed" if row.get("expose_to_model") else "hidden"
        deferred_state = row.get("deferred")
        if auto_enable and row.get("name") in enabled:
            loaded = session.tool_registry.get_tool_capabilities(str(row.get("name"))).deferred is False
            deferred_state = not loaded
        lines.append(
            f"- {row.get('name')} [{row.get('source')}] ({state}, deferred={deferred_state}, mutating={row.get('is_mutating')}, parallel={row.get('supports_parallel')})"
        )
        desc = str(row.get("description", "")).strip()
        if desc:
            lines.append(f"  {desc[:180]}")

    if enabled:
        lines.append("")
        lines.append(f"Enabled {len(enabled)} tool(s): {', '.join(enabled)}")

    return "\n".join(lines)
