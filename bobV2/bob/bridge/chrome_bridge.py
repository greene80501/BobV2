"""
Chrome Extension Bridge — WebSocket server the Chrome extension connects to.

Bob sends browser commands through this bridge; the extension executes them
in the active Chrome tab and returns results.

Protocol (JSON over WebSocket):
  Bob → Extension:  {"id": "<uuid>", "action": "<name>", "params": {...}}
  Extension → Bob:  {"id": "<uuid>", "result": "<str>"}  |  {"id": "<uuid>", "error": "<msg>"}
  Extension → Bob (on connect): {"type": "connect", "version": "1.0"}
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

logger = logging.getLogger("bob.bridge.chrome")

BRIDGE_PORT = 9876
_NOT_CONNECTED = "Chrome extension not connected."


class ChromeBridge:
    """Async WebSocket server on localhost:9876.

    Only one extension connection is kept alive at a time; a new connection
    replaces any stale one.
    """

    def __init__(self, port: int = BRIDGE_PORT) -> None:
        self.port = port
        self._enabled: bool = True
        self._server = None
        self._ws = None
        self._connected: bool = False  # set True/False in _handle_connection
        self._ws_lock: asyncio.Lock | None = None
        self._pending: dict[str, asyncio.Future] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    async def start(self) -> None:
        self._ws_lock = asyncio.Lock()
        try:
            import websockets
        except ImportError:
            logger.warning("websockets package not installed — Chrome bridge disabled")
            return

        try:
            self._server = await websockets.serve(
                self._handle_connection,
                "127.0.0.1",
                self.port,
            )
            logger.info("Chrome bridge listening on ws://localhost:%d", self.port)
        except OSError as exc:
            logger.debug("Chrome bridge could not start on port %d: %s", self.port, exc)

    async def stop(self) -> None:
        self._enabled = False
        self._connected = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._server is not None:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=2.0)
            except Exception:
                pass
            self._server = None
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    async def send_command(
        self, action: str, params: dict | None = None, *, timeout: float = 30.0
    ) -> str:
        """Send *action* to the extension and return its string result."""
        if not self._enabled:
            return _NOT_CONNECTED
        if not self.is_connected:
            return _NOT_CONNECTED

        cmd_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[cmd_id] = fut

        try:
            await self._ws.send(json.dumps({
                "id": cmd_id,
                "action": action,
                "params": params or {},
            }))
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(cmd_id, None)
            if not fut.done():
                fut.cancel()
            raise RuntimeError(f"Chrome extension timed out after {timeout}s for action '{action}'")
        except Exception:
            self._pending.pop(cmd_id, None)
            if not fut.done():
                fut.cancel()
            raise

    async def _handle_connection(self, ws) -> None:
        logger.info("Chrome extension connected")
        lock = self._ws_lock or asyncio.Lock()
        async with lock:
            old = self._ws
            if old is not None:
                try:
                    await old.close()
                except Exception:
                    pass
            self._ws = ws
            self._connected = True

        try:
            await ws.send(json.dumps({"type": "connected", "version": "1.0"}))
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg_id = msg.get("id")
                if msg_id and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if not fut.done():
                        err = msg.get("error")
                        if err:
                            fut.set_exception(RuntimeError(err))
                        else:
                            fut.set_result(msg.get("result", ""))
        except Exception as exc:
            logger.debug("Chrome extension disconnected: %s", exc)
        finally:
            async with lock:
                if self._ws is ws:
                    self._ws = None
                    self._connected = False
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(RuntimeError("Chrome extension disconnected"))
            self._pending.clear()
