from __future__ import annotations

import pytest
from types import SimpleNamespace

from bob.tools.browser import browser_handler


class _FakeBridge:
    def __init__(self, *, enabled: bool = True, connected: bool = True) -> None:
        self._enabled = enabled
        self._connected = connected
        self.calls: list[tuple[str, dict]] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def send_command(self, action: str, params: dict | None = None) -> str:
        payload = params or {}
        self.calls.append((action, payload))
        return "ok"


class _FakeSession:
    def __init__(self, bridge) -> None:
        self._chrome_bridge = bridge
        self.config = SimpleNamespace(model="vision-model")
        self._attachments: list[tuple[str, str, str, str]] = []

    def get_model_runtime(self, _model: str):
        compatibility = SimpleNamespace(supports_vision=True)
        provider_auth = SimpleNamespace()
        return compatibility, provider_auth

    async def attach_image(self, path: str, mime: str, b64: str, *, detail_level: str = "medium") -> None:
        self._attachments.append((path, mime, b64, detail_level))


class _FakeContext:
    def __init__(self, session) -> None:
        self._session = session
        self.attach_image = session.attach_image


@pytest.mark.asyncio
async def test_browser_handler_uses_session_chrome_bridge_for_commands() -> None:
    bridge = _FakeBridge()
    context = _FakeContext(_FakeSession(bridge))

    result = await browser_handler(
        {"action": "navigate", "url": "https://example.com"},
        context,
    )

    assert result == "ok"
    assert bridge.calls == [("navigate", {"url": "https://example.com"})]


@pytest.mark.asyncio
async def test_browser_handler_returns_not_connected_when_bridge_disabled() -> None:
    bridge = _FakeBridge(enabled=False, connected=True)
    context = _FakeContext(_FakeSession(bridge))

    result = await browser_handler({"action": "get_current_url"}, context)

    assert "Chrome extension not connected" in result


@pytest.mark.asyncio
async def test_browser_handler_attaches_screenshot_instead_of_returning_raw_base64() -> None:
    tiny_jpeg_b64 = "ZmFrZSBpbWFnZSBieXRlcw=="

    class _ScreenshotBridge(_FakeBridge):
        async def send_command(self, action: str, params: dict | None = None) -> str:
            self.calls.append((action, params or {}))
            return tiny_jpeg_b64

    session = _FakeSession(_ScreenshotBridge())
    context = _FakeContext(session)

    result = await browser_handler({"action": "screenshot", "quality": "low"}, context)

    assert "Screenshot attached" in result
    assert len(session._attachments) == 1
    assert session._attachments[0][3] == "low"


@pytest.mark.asyncio
async def test_browser_handler_skips_screenshot_attachment_for_non_vision_model() -> None:
    tiny_jpeg_b64 = "ZmFrZSBpbWFnZSBieXRlcw=="

    class _ScreenshotBridge(_FakeBridge):
        async def send_command(self, action: str, params: dict | None = None) -> str:
            self.calls.append((action, params or {}))
            return tiny_jpeg_b64

    class _NonVisionSession(_FakeSession):
        def get_model_runtime(self, _model: str):
            compatibility = SimpleNamespace(supports_vision=False)
            provider_auth = SimpleNamespace()
            return compatibility, provider_auth

    session = _NonVisionSession(_ScreenshotBridge())
    context = _FakeContext(session)

    result = await browser_handler({"action": "screenshot"}, context)

    assert "not configured for vision" in result
    assert session._attachments == []
