from __future__ import annotations

from typing import Any


DEMO_MCP_TOOLS: list[dict[str, Any]] = [
    {
        "server_name": "github",
        "name": "search_issues",
        "description": "Search repository issues and pull requests with filters for author, label, and state.",
    },
    {
        "server_name": "github",
        "name": "read_pull_request",
        "description": "Fetch pull request metadata, changed files, review comments, and check status.",
    },
    {
        "server_name": "filesystem",
        "name": "read_project_file",
        "description": "Read files from the active workspace using normalized relative paths.",
    },
    {
        "server_name": "filesystem",
        "name": "search_workspace",
        "description": "Run indexed filename and text search across the current project tree.",
    },
    {
        "server_name": "postgres",
        "name": "query_database",
        "description": "Execute read-only SQL queries against the configured application database.",
    },
    {
        "server_name": "browser",
        "name": "inspect_page",
        "description": "Inspect the active browser tab, including URL, title, visible text, and selected element state.",
    },
]


def list_demo_mcp_tools(server_name: str | None = None) -> list[dict[str, Any]]:
    if not server_name:
        return [dict(tool) for tool in DEMO_MCP_TOOLS]
    wanted = server_name.strip().lower()
    return [
        dict(tool)
        for tool in DEMO_MCP_TOOLS
        if str(tool["server_name"]).lower() == wanted
    ]
