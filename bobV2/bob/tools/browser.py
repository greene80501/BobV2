"""Browser control tool — controls the user's Chrome via the Chrome extension bridge."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bob.core.session import ToolContext

BROWSER_DESCRIPTION = """\
Control the user's Chrome browser via the bob Chrome extension (ws://localhost:9876).

IMPORTANT — use web_fetch instead of this tool for any public page you can read directly.
Only use browser when one of these is true:
  1. The page requires the user's active login session (LinkedIn feed, Gmail, Twitter timeline,
     private dashboards). The user's Chrome already has the session; web_fetch does not.
  2. web_fetch returned a 403, an empty page, or clearly broken/JS-only content.
  3. The task requires interaction: scrolling to load more content, clicking elements,
     filling forms, or navigating through authenticated flows.

Do NOT use browser for (use web_fetch instead):
  - GitHub repos, files, READMEs, commit history — web_fetch reads these perfectly.
  - Personal/portfolio websites, landing pages, marketing sites.
  - Documentation sites, blog posts, news articles, PDFs.
  - Any public static page where you just need to read content.

Actions available (once you've determined browser is needed):
  - get_page_text — fast, low-cost; use for articles, docs, structured text.
  - get_page_html — raw HTML; use when you need to parse structure.
  - navigate → then get_page_text or get_page_html in separate calls.
  - scroll — scroll the page; y=500 scrolls down ~one screen, y=-500 scrolls up.
    Use scroll (not execute_js) for scrolling — it works on SPAs like LinkedIn and Twitter.
  - click, form_input, find_elements — for interaction with page elements.
  - type_text — type text into the currently focused element (or a given selector).
    Works for standard inputs AND rich text editors (Google Docs, Notion, CodeMirror).
    Use instead of execute_js for typing — not blocked by CSP.
  - screenshot — EXPENSIVE: costs ~100k–500k tokens on text-only models and may exceed
    the context window entirely. Only use when visual layout genuinely cannot be inferred
    from text (e.g. diagrams, captchas, canvas). For profiles, articles, tables, or any
    readable content, always use get_page_text or get_page_html instead.

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
    },
    "required": ["action"],
}

_NOT_CONNECTED = (
    "Chrome extension not connected. Ask the user to open the bob Chrome extension "
    "in their browser. Once connected, you can control their active Chrome tab."
)

# ~50k tokens — safe ceiling for base64 image data in context
_SCREENSHOT_MAX_CHARS = 200_000


def _compress_or_reject_screenshot(raw: str) -> str:
    """Try to resize the screenshot to fit within _SCREENSHOT_MAX_CHARS.

    Attempts progressively lower resolutions/quality using Pillow.
    Returns a guidance message if Pillow is unavailable or the image
    cannot be compressed small enough.
    """
    try:
        import base64 as _b64
        import io as _io
        from PIL import Image as _Image  # type: ignore[import]

        # Strip data URL prefix if present (data:image/png;base64,...)
        b64 = raw.split(",", 1)[1] if "," in raw else raw
        img = _Image.open(_io.BytesIO(_b64.b64decode(b64))).convert("RGB")

        for max_w, quality in [(960, 75), (640, 60), (480, 50)]:
            if img.width > max_w:
                ratio = max_w / img.width
                img = img.resize((max_w, int(img.height * ratio)), _Image.LANCZOS)
            buf = _io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            compressed = _b64.b64encode(buf.getvalue()).decode()
            if len(compressed) <= _SCREENSHOT_MAX_CHARS:
                return compressed
    except ImportError:
        pass
    except Exception:
        pass

    return (
        f"Screenshot captured but too large to include in context "
        f"({len(raw):,} chars ≈ {len(raw) // 4:,} tokens — model limit would be exceeded). "
        "Use get_page_text to read this page as text instead."
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
        if action == "screenshot" and len(result) > _SCREENSHOT_MAX_CHARS:
            result = _compress_or_reject_screenshot(result)
        return result
    except RuntimeError as exc:
        return f"Browser error: {exc}"
