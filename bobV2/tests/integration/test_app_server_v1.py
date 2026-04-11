from __future__ import annotations

import asyncio

from bob.app_server.server import AppServer


def test_server_capabilities_exposes_v1_methods():
    async def _run() -> None:
        server = AppServer()
        await server.start()
        try:
            resp = await server.handle_message(
                {"jsonrpc": "2.0", "id": 1, "method": "server.capabilities", "params": {}}
            )
            assert resp is not None
            assert "result" in resp
            result = resp["result"]
            assert result["protocol_version"] == "1.0"
            assert "threads.create" in result["methods"]
            assert "turns.submit" in result["methods"]
        finally:
            await server.stop()

    asyncio.run(_run())


def test_legacy_and_task_routes():
    async def _run() -> None:
        server = AppServer()
        await server.start()
        try:
            ping = await server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "ping",
                    "params": {},
                }
            )
            assert ping is not None
            assert ping["result"]["pong"] is True

            task_created = await server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tasks.create",
                    "params": {
                        "type": "local_shell",
                        "payload": {"command": "echo bob"},
                        "max_attempts": 1,
                    },
                }
            )
            assert task_created is not None
            task_id = task_created["result"]["task"]["id"]

            listed = await server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tasks.list",
                    "params": {},
                }
            )
            assert listed is not None
            assert any(x["id"] == task_id for x in listed["result"]["tasks"])

            legacy = await server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "bob.config.get",
                    "params": {},
                }
            )
            assert legacy is not None
            assert "config" in legacy["result"]
        finally:
            await server.stop()

    asyncio.run(_run())
