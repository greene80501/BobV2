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


def test_agent_routes():
    async def _run() -> None:
        server = AppServer()
        await server.start()
        try:
            created = await server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "threads.create",
                    "params": {"ephemeral": False},
                }
            )
            assert created is not None
            thread_id = created["result"]["thread"]["id"]

            spawned = await server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 11,
                    "method": "agents.spawn",
                    "params": {
                        "thread_id": thread_id,
                        "description": "Inspect repository",
                        "prompt": "Inspect the repository and report likely risk areas.",
                        "subagent_type": "explore",
                    },
                }
            )
            assert spawned is not None
            agent_id = spawned["result"]["agent"]["task_id"]
            assert spawned["result"]["agent"]["agent_type"] == "explore"
            assert spawned["result"]["agent"]["title"] == "Inspect repository"

            listed = await server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 12,
                    "method": "agents.list",
                    "params": {"thread_id": thread_id},
                }
            )
            assert listed is not None
            assert any(agent["agent_id"] == agent_id for agent in listed["result"]["agents"])

            waited = await server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 13,
                    "method": "agents.wait",
                    "params": {"thread_id": thread_id, "task_ids": [agent_id], "timeout_ms": 1000},
                }
            )
            assert waited is not None
            assert agent_id in waited["result"]["results"]
        finally:
            await server.stop()

    asyncio.run(_run())
