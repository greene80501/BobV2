from __future__ import annotations

import asyncio
import base64
import io
from typing import Any

COMPUTER_USE_DESCRIPTION = (
    "Control the GUI: take screenshots, move the mouse, click, type text, and "
    "press keyboard shortcuts. Only registered when the user has enabled "
    "feature_flags.computer_use=true in their config."
)

COMPUTER_USE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "screenshot",
                "left_click",
                "right_click",
                "double_click",
                "mouse_move",
                "scroll",
                "key",
                "type",
                "cursor_position",
            ],
            "description": "The GUI action to perform.",
        },
        "coordinate": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "[x, y] screen coordinates (required for click/move/scroll).",
        },
        "text": {
            "type": "string",
            "description": "Text to type or key combination to press (e.g. 'ctrl+c').",
        },
        "direction": {
            "type": "string",
            "enum": ["up", "down", "left", "right"],
            "description": "Scroll direction (for 'scroll' action).",
        },
        "amount": {
            "type": "integer",
            "description": "Scroll amount in clicks (default: 3).",
        },
    },
    "required": ["action"],
}

_MUTATING_ACTIONS = frozenset(
    ["left_click", "right_click", "double_click", "mouse_move", "scroll", "key", "type"]
)


async def computer_use_handler(tool_input: dict, context: Any) -> str:
    action: str = tool_input.get("action", "")
    if not action:
        return "Error: action is required"

    if action == "screenshot":
        return await _take_screenshot()
    elif action == "cursor_position":
        return await _cursor_position()
    elif action in _MUTATING_ACTIONS:
        return await _perform_action(action, tool_input)
    else:
        return f"Error: unknown action '{action}'"


_SCREENSHOT_MAX_WIDTH = 640    # cap width; height scales proportionally
_SCREENSHOT_JPEG_QUALITY = 15  # very low quality — UI is still legible, ~5-10 KB


async def _take_screenshot() -> str:
    """Capture the screen, resize, and return a compact base64-encoded JPEG.

    Full-res PNGs are ~500 KB / 175 K tokens as text.
    At 1280 px wide, JPEG q=35 is ~25-40 KB / ~6-8 K tokens — 20× smaller.
    """
    loop = asyncio.get_running_loop()
    try:
        import mss

        def _grab() -> tuple[bytes, str]:
            with mss.mss() as sct:
                monitor = sct.monitors[0]
                raw = sct.grab(monitor)
                w, h = raw.size

                try:
                    from PIL import Image
                    import io as _io

                    # mss gives BGRA; convert to RGB for PIL
                    img = Image.frombytes("RGB", (w, h), raw.bgra, "raw", "BGRX")

                    if img.width > _SCREENSHOT_MAX_WIDTH:
                        ratio = _SCREENSHOT_MAX_WIDTH / img.width
                        img = img.resize(
                            (_SCREENSHOT_MAX_WIDTH, int(img.height * ratio)),
                            Image.LANCZOS,
                        )

                    buf = _io.BytesIO()
                    img.save(buf, format="JPEG", quality=_SCREENSHOT_JPEG_QUALITY, optimize=True)
                    return buf.getvalue(), "jpeg"

                except ImportError:
                    # PIL not available — fall back to PNG (larger but functional)
                    import mss.tools as _mss_tools
                    return _mss_tools.to_png(raw.rgb, raw.size), "png"

        img_bytes, fmt = await loop.run_in_executor(None, _grab)
        b64 = base64.b64encode(img_bytes).decode()
        size_kb = len(img_bytes) // 1024
        return f"data:image/{fmt};base64,{b64}\n[{fmt.upper()}, {size_kb} KB, {_SCREENSHOT_MAX_WIDTH}px max-width]"

    except ImportError:
        return "Error: mss is not installed. Run: pip install mss"
    except Exception as exc:
        return f"Error taking screenshot: {exc}"


async def _cursor_position() -> str:
    loop = asyncio.get_running_loop()
    try:
        import pyautogui

        pos = await loop.run_in_executor(None, pyautogui.position)
        return f"Cursor position: x={pos.x}, y={pos.y}"
    except ImportError:
        return "Error: pyautogui is not installed. Run: pip install pyautogui"
    except Exception as exc:
        return f"Error getting cursor position: {exc}"


async def _perform_action(action: str, tool_input: dict) -> str:
    loop = asyncio.get_running_loop()
    try:
        import pyautogui

        coordinate = tool_input.get("coordinate")
        text = tool_input.get("text", "")
        direction = tool_input.get("direction", "down")
        amount = int(tool_input.get("amount", 3))

        def _run() -> str:
            if action == "left_click":
                if not coordinate or len(coordinate) < 2:
                    return "Error: coordinate [x, y] required for left_click"
                pyautogui.click(coordinate[0], coordinate[1])
                return f"Left-clicked at ({coordinate[0]}, {coordinate[1]})"

            elif action == "right_click":
                if not coordinate or len(coordinate) < 2:
                    return "Error: coordinate [x, y] required for right_click"
                pyautogui.rightClick(coordinate[0], coordinate[1])
                return f"Right-clicked at ({coordinate[0]}, {coordinate[1]})"

            elif action == "double_click":
                if not coordinate or len(coordinate) < 2:
                    return "Error: coordinate [x, y] required for double_click"
                pyautogui.doubleClick(coordinate[0], coordinate[1])
                return f"Double-clicked at ({coordinate[0]}, {coordinate[1]})"

            elif action == "mouse_move":
                if not coordinate or len(coordinate) < 2:
                    return "Error: coordinate [x, y] required for mouse_move"
                pyautogui.moveTo(coordinate[0], coordinate[1])
                return f"Moved mouse to ({coordinate[0]}, {coordinate[1]})"

            elif action == "scroll":
                if not coordinate or len(coordinate) < 2:
                    return "Error: coordinate [x, y] required for scroll"
                clicks = amount if direction == "up" else -amount
                pyautogui.scroll(clicks, x=coordinate[0], y=coordinate[1])
                return f"Scrolled {direction} {amount} clicks at ({coordinate[0]}, {coordinate[1]})"

            elif action == "key":
                if not text:
                    return "Error: text (key combination) required for key action"
                pyautogui.hotkey(*text.split("+"))
                return f"Pressed key(s): {text}"

            elif action == "type":
                if not text:
                    return "Error: text required for type action"
                pyautogui.typewrite(text, interval=0.02)
                return f"Typed {len(text)} characters"

            return f"Error: unhandled action '{action}'"

        return await loop.run_in_executor(None, _run)
    except ImportError:
        return "Error: pyautogui is not installed. Run: pip install pyautogui"
    except Exception as exc:
        return f"Error performing '{action}': {exc}"
