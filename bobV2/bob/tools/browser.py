"""Browser control tool — controls the user's Chrome via the Chrome extension bridge."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bob.core.session import ToolContext

BROWSER_DESCRIPTION = """\
Control the user's Chrome browser via the bob Chrome extension (ws://localhost:9876).

Decision guide — pick the lightest action that works:
- For research/lookups: use web_search or web_fetch first (no extension needed).
- For live pages, SPAs, login flows, or when web_fetch is blocked: use this tool.
- get_page_text — fast, low-cost; use for articles, docs, structured text.
- screenshot — returns base64 PNG; use when layout/visuals matter or text is insufficient.
- get_page_html — raw HTML; use when you need to parse structure.
- navigate → then get_page_text or screenshot in separate calls.

If the extension is not connected this tool returns a message. Do not retry —
report it to the user and ask them to open the bob Chrome extension in Chrome.
"""

BROWSER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "navigate",
                "get_page_text",
                "get_page_html",
                "screenshot",
                "click",
                "form_input",
                "execute_js",
                "find_elements",
                "scroll",
                "get_current_url",
            ],
            "description": "Browser action to perform.",
        },
        "url": {
            "type": "string",
            "description": "URL to navigate to. Required for 'navigate'.",
        },
        "selector": {
            "type": "string",
            "description": "CSS selector. Required for 'click', 'form_input', 'find_elements'.",
        },
        "value": {
            "type": "string",
            "description": "Text to enter. Required for 'form_input'.",
        },
        "code": {
            "type": "string",
            "description": "JavaScript expression to evaluate. Required for 'execute_js'.",
        },
        "limit": {
            "type": "integer",
            "default": 20,
            "description": "Max elements to return for 'find_elements'.",
        },
        "x": {
            "type": "integer",
            "default": 0,
            "description": "Horizontal scroll offset in pixels for 'scroll'.",
        },
        "y": {
            "type": "integer",
            "default": 0,
            "description": "Vertical scroll offset in pixels for 'scroll'.",
        },
    },
    "required": ["action"],
}

_NOT_CONNECTED = (
    "Chrome extension not connected. Ask the user to open the bob Chrome extension "
    "in their browser. Once connected, you can control their active Chrome tab."
)


async def browser_handler(tool_input: dict, context: "ToolContext") -> str:
    session = context._session
    bridge = getattr(session, "_chrome_bridge", None)
    if bridge is None or not bridge._enabled:
        return _NOT_CONNECTED

    if not bridge.is_connected:
        return _NOT_CONNECTED

    action = tool_input.get("action", "")
    params: dict[str, Any] = {}

    if action == "navigate":
        params["url"] = tool_input.get("url", "")
    elif action in ("click", "find_elements"):
        params["selector"] = tool_input.get("selector", "")
        if action == "find_elements":
            params["limit"] = tool_input.get("limit", 20)
    elif action == "form_input":
        params["selector"] = tool_input.get("selector", "")
        params["value"] = tool_input.get("value", "")
    elif action == "execute_js":
        params["code"] = tool_input.get("code", "")
    elif action == "scroll":
        params["x"] = tool_input.get("x", 0)
        params["y"] = tool_input.get("y", 0)

    try:
        return await bridge.send_command(action, params)
    except RuntimeError as exc:
        return f"Browser error: {exc}"
