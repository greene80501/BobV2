from __future__ import annotations

from typing import Any

MCP_AUTHENTICATE_DESCRIPTION = (
    "Authenticate with an MCP server using OAuth 2.0 PKCE flow. Opens a browser "
    "window for the user to authorize, then saves the token to the session config. "
    "Use this when an MCP server requires authentication."
)

MCP_AUTHENTICATE_SCHEMA = {
    "type": "object",
    "properties": {
        "server_name": {
            "type": "string",
            "description": "Name of the MCP server to authenticate with.",
        },
        "auth_server_url": {
            "type": "string",
            "description": "Base URL of the OAuth 2.0 authorization server (e.g. https://auth.example.com).",
        },
        "client_id": {
            "type": "string",
            "description": "OAuth 2.0 client ID registered for bob.",
        },
        "scope": {
            "type": "string",
            "description": "Space-separated OAuth scopes to request (optional).",
        },
    },
    "required": ["server_name", "auth_server_url", "client_id"],
}


async def mcp_authenticate_handler(tool_input: dict, context: Any) -> str:
    server_name: str = tool_input.get("server_name", "").strip()
    auth_server_url: str = tool_input.get("auth_server_url", "").strip()
    client_id: str = tool_input.get("client_id", "").strip()
    scope: str = tool_input.get("scope", "").strip()

    if not server_name:
        return "Error: server_name is required"
    if not auth_server_url:
        return "Error: auth_server_url is required"
    if not client_id:
        return "Error: client_id is required"

    from bob.mcp.oauth import McpOAuthFlow

    flow = McpOAuthFlow(
        server_name=server_name,
        auth_server_url=auth_server_url,
        client_id=client_id,
        scope=scope,
    )

    try:
        token = await flow.run_flow()
    except Exception as exc:
        return f"OAuth flow failed: {exc}"

    # Persist the token to the session's in-memory config
    session = getattr(context, "_session", None)
    if session is not None:
        session.config.mcp_auth_tokens[server_name] = token

    # Also persist to config file
    try:
        from bob.config.editor import set_value
        set_value(f"mcp_auth_tokens.{server_name}", token)
    except Exception:
        pass

    return f"Authenticated with MCP server '{server_name}'. Token saved."
