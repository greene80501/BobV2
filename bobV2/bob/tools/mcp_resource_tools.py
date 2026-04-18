from __future__ import annotations

from typing import Any

MCP_LIST_RESOURCES_DESCRIPTION = (
    "List all resources exposed by connected MCP servers. Resources are "
    "read-only data sources (files, database records, API responses) that "
    "MCP servers make available alongside their tools."
)

MCP_LIST_RESOURCES_SCHEMA = {
    "type": "object",
    "properties": {
        "server_name": {
            "type": "string",
            "description": "Filter to a specific MCP server name (optional).",
        },
    },
}

MCP_READ_RESOURCE_DESCRIPTION = (
    "Read the contents of a resource from an MCP server. Use mcp_list_resources "
    "first to discover available resource URIs."
)

MCP_READ_RESOURCE_SCHEMA = {
    "type": "object",
    "properties": {
        "server_name": {
            "type": "string",
            "description": "Name of the MCP server that owns the resource.",
        },
        "uri": {
            "type": "string",
            "description": "URI of the resource to read (e.g. 'file:///path/to/file').",
        },
    },
    "required": ["server_name", "uri"],
}


async def mcp_list_resources_handler(tool_input: dict, context: Any) -> str:
    session = getattr(context, "_session", None)
    mcp_manager = getattr(session, "_mcp_manager", None)
    if mcp_manager is None:
        return "No MCP manager available — no MCP servers are configured."

    server_filter: str = tool_input.get("server_name", "").strip()
    resources = mcp_manager.get_all_resources()

    if server_filter:
        resources = [r for r in resources if r.server_name == server_filter]

    if not resources:
        if server_filter:
            return f"No resources found on MCP server '{server_filter}'."
        return "No resources found across connected MCP servers."

    lines = [f"Found {len(resources)} resource(s):\n"]
    for r in resources:
        lines.append(f"  server: {r.server_name}")
        lines.append(f"  name:   {r.name}")
        lines.append(f"  uri:    {r.uri}")
        if r.description:
            lines.append(f"  desc:   {r.description}")
        if r.mime_type:
            lines.append(f"  type:   {r.mime_type}")
        lines.append("")
    return "\n".join(lines).strip()


async def mcp_read_resource_handler(tool_input: dict, context: Any) -> str:
    server_name: str = tool_input.get("server_name", "").strip()
    uri: str = tool_input.get("uri", "").strip()

    if not server_name:
        return "Error: server_name is required"
    if not uri:
        return "Error: uri is required"

    session = getattr(context, "_session", None)
    mcp_manager = getattr(session, "_mcp_manager", None)
    if mcp_manager is None:
        return "No MCP manager available — no MCP servers are configured."

    return await mcp_manager.read_resource(server_name, uri)
