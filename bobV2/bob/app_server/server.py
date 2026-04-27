from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from bob.app_server.context import ConnectionContext, RequestContext
from bob.app_server.errors import AppServerError
from bob.app_server.event_bus import EventRecord, EventBus
from bob.app_server.middleware import auth_middleware, run_middleware_chain, tracing_middleware, validation_middleware
from bob.app_server.registry import SessionRegistry
from bob.app_server.router import RpcRouter
from bob.app_server.routes import ALL_ROUTE_MODULES
from bob.app_server.schemas import JsonRpcRequest, JsonRpcResponse
from bob.core.tasks import TaskRuntime


class AppServer:
    def __init__(self, logger=None) -> None:
        self.logger = logger
        self.router = RpcRouter()
        self.event_bus = EventBus(Path.home() / ".bob" / "app_events.sqlite")
        self.registry = SessionRegistry(self.event_bus)
        self.task_runtime = TaskRuntime(
            db_path=Path.home() / ".bob" / "tasks_runtime.sqlite",
            event_bus=self.event_bus,
            registry=self.registry,
        )
        self.middleware = [validation_middleware, auth_middleware, tracing_middleware]
        self._started = False
        self._register_routes()

    def _register_routes(self) -> None:
        for mod in ALL_ROUTE_MODULES:
            mod.register(self.router)

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        await self.event_bus.start()
        await self.task_runtime.start()

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        await self.task_runtime.stop()
        await self.registry.shutdown_all()
        await self.event_bus.stop()

    async def handle_message(
        self,
        raw: dict[str, Any],
        *,
        connection: Optional[ConnectionContext] = None,
    ) -> Optional[dict[str, Any]]:
        req_id = raw.get("id")
        try:
            request = JsonRpcRequest.model_validate(raw)
        except Exception:
            return self._error_response(req_id, -32600, "Invalid request")

        ctx = RequestContext(
            registry=self.registry,
            event_bus=self.event_bus,
            task_runtime=self.task_runtime,
            router=self.router,
            connection=connection,
            logger=self.logger,
        )

        try:
            result = await run_middleware_chain(
                ctx,
                request,
                endpoint=lambda: self.router.dispatch(ctx, request.method, request.params),
                middleware=self.middleware,
            )
        except AppServerError as exc:
            if request.id is None:
                return None
            return {"jsonrpc": "2.0", "id": request.id, "error": exc.to_jsonrpc()}
        except Exception as exc:
            if request.id is None:
                return None
            return self._error_response(request.id, -32000, str(exc))

        if request.id is None:
            return None
        return JsonRpcResponse(id=request.id, result=result).model_dump(exclude_none=True)

    def _error_response(self, req_id: Any, code: int, message: str, data: Optional[dict] = None) -> dict:
        payload: dict[str, Any] = {"code": code, "message": message}
        if data:
            payload["data"] = data
        return JsonRpcResponse(id=req_id, error=payload).model_dump(exclude_none=True)


async def run_stdio_server() -> None:
    server = AppServer()
    await server.start()
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    stdout_lock = asyncio.Lock()

    async def write_response(obj: dict) -> None:
        async with stdout_lock:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            line_s = line.decode("utf-8", errors="replace").strip()
            if not line_s:
                continue
            try:
                msg = json.loads(line_s)
            except json.JSONDecodeError:
                await write_response(server._error_response(None, -32700, "Parse error"))
                continue
            response = await server.handle_message(msg)
            if response is not None:
                await write_response(response)
    finally:
        await server.stop()


async def _forward_subscription(
    conn: ConnectionContext,
    sub_id: str,
    queue: asyncio.Queue[EventRecord],
) -> None:
    while True:
        rec = await queue.get()
        envelope = {
            "jsonrpc": "2.0",
            "method": "realtime.event",
            "params": {
                "type": "realtime.event",
                "subscription_id": sub_id,
                "cursor": rec.cursor,
                "channels": rec.channels,
                "event": rec.event,
            },
        }
        await conn.ws.send(json.dumps(envelope))


async def _heartbeat_task(conn: ConnectionContext) -> None:
    while True:
        msg = {
            "jsonrpc": "2.0",
            "method": "realtime.heartbeat",
            "params": {
                "type": "realtime.heartbeat",
                "connection_id": conn.id,
                "ts_ms": int(time.time() * 1000),
            },
        }
        await conn.ws.send(json.dumps(msg))
        await asyncio.sleep(20)


async def run_websocket_server(port: int = 8765, host: str = "localhost") -> None:
    try:
        import websockets  # type: ignore[import]
    except ImportError:
        print("websockets is not installed. Run: pip install websockets", file=sys.stderr)
        return

    server = AppServer()
    await server.start()

    async def handler(websocket):
        conn = ConnectionContext(id=str(uuid.uuid4()), ws=websocket)
        hb = asyncio.create_task(_heartbeat_task(conn))
        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps(server._error_response(None, -32700, "Parse error")))
                    continue
                response = await server.handle_message(msg, connection=conn)
                if response is not None:
                    await websocket.send(json.dumps(response))

                # Start forwarders lazily for any newly-added subscriptions.
                for sub_id, meta in list(conn.subscriptions.items()):
                    if sub_id in conn.forwarder_tasks:
                        continue
                    conn.forwarder_tasks[sub_id] = asyncio.create_task(
                        _forward_subscription(conn, sub_id, meta["queue"])
                    )
        finally:
            hb.cancel()
            for sub_id in list(conn.subscriptions.keys()):
                await server.event_bus.unsubscribe(sub_id)
            for task in list(conn.forwarder_tasks.values()):
                task.cancel()
            for task in list(conn.forwarder_tasks.values()):
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    print(f"bob app-server listening on ws://{host}:{port}", flush=True)
    try:
        async with websockets.serve(handler, host, port):
            await asyncio.Future()
    finally:
        await server.stop()


async def run_server(stdio: bool = False, port: int = 8765, host: str = "localhost") -> None:
    if stdio:
        await run_stdio_server()
    else:
        await run_websocket_server(port=port, host=host)
