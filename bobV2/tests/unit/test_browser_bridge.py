from __future__ import annotations

import pytest

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


class _FakeContext:
    def __init__(self, session) -> None:
        self._session = session


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
