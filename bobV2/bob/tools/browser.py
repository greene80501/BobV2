"""Browser control tool that uses the Chrome extension bridge."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bob.core.image_payloads import prepare_base64_image_for_model

if TYPE_CHECKING:
    from bob.core.session import ToolContext


BROWSER_DESCRIPTION = """\
Control the user's Chrome browser via the bob Chrome extension (ws://localhost:9876).

IMPORTANT - use web_fetch instead of this tool for any public page you can read directly.
Only use browser when one of these is true:
  1. The page requires the user's active login session (LinkedIn feed, Gmail, Twitter timeline,
     private dashboards). The user's Chrome already has the session; web_fetch does not.
  2. web_fetch returned a 403, an empty page, or clearly broken/JS-only content.
  3. The task requires interaction: scrolling to load more content, clicking elements,
     filling forms, or navigating through authenticated flows.

Do NOT use browser for (use web_fetch instead):
  - GitHub repos, files, READMEs, commit history - web_fetch reads these perfectly.
  - Personal/portfolio websites, landing pages, marketing sites.
  - Documentation sites, blog posts, news articles, PDFs.
  - Any public static page where you just need to read content.

Actions available (once you've determined browser is needed):
  - get_page_text - fast, low-cost; use for articles, docs, structured text.
  - get_page_html - raw HTML; use when you need to parse structure.
  - navigate -> then get_page_text or get_page_html in separate calls.
  - scroll - scroll the page; y=500 scrolls down about one screen, y=-500 scrolls up.
    Use scroll (not execute_js) for scrolling - it works on SPAs like LinkedIn and Twitter.
  - click, form_input, find_elements - for interaction with page elements.
  - type_text - type text into the currently focused element (or a given selector).
    Works for standard inputs AND rich text editors (Google Docs, Notion, CodeMirror).
    Use instead of execute_js for typing - not blocked by CSP.
  - screenshot - expensive. On vision-capable models Bob attaches the screenshot as an image
    using low/medium/high detail. On non-vision models Bob refuses to dump raw base64 into
    context because that bloats tokens without giving the model usable visual understanding.

If the extension is not connected this tool returns a message. Do not retry -
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
                "type_text",
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
        "text": {
            "type": "string",
            "description": "Text to type. Required for 'type_text'.",
        },
        "quality": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "Optional screenshot detail level. When omitted, Bob auto-picks based on context pressure.",
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
    elif action == "type_text":
        params["text"] = tool_input.get("text", "")
        if tool_input.get("selector"):
            params["selector"] = tool_input["selector"]

    try:
        result = await bridge.send_command(action, params)
        if action == "screenshot":
            compatibility, _ = session.get_model_runtime(session.config.model)
            if not getattr(compatibility, "supports_vision", False):
                return (
                    f"Screenshot captured, but current model '{session.config.model}' is not configured for vision. "
                    "Bob skipped attaching the raw image to avoid bloating context. "
                    "Use get_page_text/get_page_html or switch to a vision-capable model."
                )

            prepared = prepare_base64_image_for_model(
                result,
                session=session,
                prompt_text="screenshot visual inspection",
                requested=tool_input.get("quality"),
            )
            attach = getattr(context, "attach_image", None)
            if attach is None:
                return (
                    f"Screenshot prepared (detail={prepared.detail_level}, "
                    f"approx_tokens={prepared.approx_tokens:,}) but attachment is not supported in this mode."
                )
            await attach(
                "browser-screenshot",
                prepared.mime,
                prepared.data_url.split(",", 1)[1],
                detail_level=prepared.detail_level,
            )
            return (
                f"Screenshot attached: detail={prepared.detail_level}, "
                f"approx_tokens={prepared.approx_tokens:,}, mime={prepared.mime}"
            )
        return result
    except RuntimeError as exc:
        return f"Browser error: {exc}"
