from __future__ import annotations
import asyncio
import json
import sys
import uuid
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Request dispatch
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Any] = {}


def _register(method: str):
    """Decorator that registers a JSON-RPC handler function."""
    def decorator(fn):
        _HANDLERS[method] = fn
        return fn
    return decorator


@_register("ping")
async def _ping(params: dict) -> dict:
    return {"pong": True}


@_register("bob.session.create")
async def _session_create(params: dict) -> dict:
    return {"session_id": str(uuid.uuid4()), "status": "created"}


@_register("bob.session.submit")
async def _session_submit(params: dict) -> dict:
    return {"status": "queued", "submission_id": str(uuid.uuid4())}


@_register("bob.session.interrupt")
async def _session_interrupt(params: dict) -> dict:
    return {"status": "ok"}


@_register("bob.session.shutdown")
async def _session_shutdown(params: dict) -> dict:
    return {"status": "ok"}


@_register("bob.config.get")
async def _config_get(params: dict) -> dict:
    return {"config": {}}


@_register("bob.models.list")
async def _models_list(params: dict) -> dict:
    from bob.llm.catalog import get_catalog
    from bob.llm.compatibility import (
        get_compatibility_matrix_rows,
        get_model_compatibility,
        get_picker_seed_models,
    )

    rows: dict[str, dict[str, Any]] = {}
    for seed in get_picker_seed_models():
        rows[seed["model_id"]] = dict(seed)

    catalog = get_catalog()
    for row in catalog.list_models(status="active") if catalog.is_populated() else []:
        compat = get_model_compatibility(row["model_id"], catalog_provider=row.get("provider"))
        merged = dict(row)
        merged["route"] = compat.route.value
        merged["support_level"] = compat.support_level.value
        rows[row["model_id"]] = {**rows.get(row["model_id"], {}), **merged}

    models = sorted(
        rows.values(),
        key=lambda row: (str(row.get("provider", "")), str(row.get("model_id", ""))),
    )
    return {
        "models": models,
        "compatibility_matrix": get_compatibility_matrix_rows(),
    }


async def handle_request(msg: dict) -> Optional[dict]:
    """Handle a single JSON-RPC 2.0 request object.

    Returns a response dict for requests (those with an ``id``), or ``None``
    for notifications (no ``id``).
    """
    if not isinstance(msg, dict):
        return _error_response(None, -32600, "Invalid request")

    jsonrpc = msg.get("jsonrpc")
    if jsonrpc != "2.0":
        return _error_response(None, -32600, "Invalid JSON-RPC version")

    method = msg.get("method", "")
    req_id = msg.get("id")  # None for notifications
    params = msg.get("params") or {}

    handler = _HANDLERS.get(method)
    if handler is None:
        if req_id is not None:
            return _error_response(req_id, -32601, f"Method not found: {method!r}")
        return None

    try:
        result = await handler(params)
    except Exception as exc:
        if req_id is not None:
            return _error_response(req_id, -32000, str(exc))
        return None

    if req_id is not None:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    return None  # notification — no response


# ---------------------------------------------------------------------------
# Transport: stdio
# ---------------------------------------------------------------------------

async def run_stdio_server() -> None:
    """Serve JSON-RPC 2.0 requests from stdin, write responses to stdout.

    One JSON object per line (newline-delimited JSON).
    """
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    stdout_writer_lock = asyncio.Lock()

    async def write_response(obj: dict) -> None:
        async with stdout_writer_lock:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

    while True:
        try:
            line = await reader.readline()
        except Exception:
            break
        if not line:
            break
        line_str = line.decode("utf-8", errors="replace").strip()
        if not line_str:
            continue
        try:
            msg = json.loads(line_str)
        except json.JSONDecodeError:
            await write_response(_error_response(None, -32700, "Parse error"))
            continue
        response = await handle_request(msg)
        if response is not None:
            await write_response(response)


# ---------------------------------------------------------------------------
# Transport: WebSocket
# ---------------------------------------------------------------------------

async def run_websocket_server(port: int = 8765, host: str = "localhost") -> None:
    """Serve JSON-RPC 2.0 requests over WebSocket.

    Requires the ``websockets`` package (``pip install websockets``).
    """
    try:
        import websockets  # type: ignore[import]
    except ImportError:
        print(
            "websockets is not installed. Run: pip install websockets",
            file=sys.stderr,
        )
        return

    async def handler(websocket):
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send(json.dumps(_error_response(None, -32700, "Parse error")))
                continue
            response = await handle_request(msg)
            if response is not None:
                await websocket.send(json.dumps(response))

    print(f"bob app-server listening on ws://{host}:{port}", flush=True)
    async with websockets.serve(handler, host, port):
        await asyncio.Future()  # run forever


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_server(stdio: bool = False, port: int = 8765, host: str = "localhost") -> None:
    """Run the bob app server over the selected transport.

    Parameters
    ----------
    stdio:
        When True, use stdin/stdout (newline-delimited JSON-RPC 2.0).
        When False (default), start a WebSocket server.
    port:
        WebSocket port (ignored when ``stdio=True``).
    host:
        WebSocket bind host (ignored when ``stdio=True``).
    """
    if stdio:
        await run_stdio_server()
    else:
        await run_websocket_server(port=port, host=host)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error_response(req_id: Any, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }
