from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

# Signature: async def handler(tool_input: dict, context: Any) -> str
ToolHandler = Callable[[dict, Any], Awaitable[str]]
ToolLoader = Callable[[], Awaitable[ToolHandler | None] | ToolHandler | None]


@dataclass
class RegisteredTool:
    """Metadata + handler for a single registered tool."""

    name: str
    description: str
    input_schema: dict
    handler: ToolHandler
    is_mutating: bool = True
    supports_parallel: bool = False
    requires_network_approval: bool = False
    emits_exec_events: bool = False
    expose_to_model: bool = True
    discoverable: bool = True
    deferred: bool = False
    source: str = "core"
    keywords: list[str] | None = None
    loader: ToolLoader | None = None


class ToolRegistry:
    """
    Central registry for all tools available to the agent.

    Tools are registered with a JSON Schema for their inputs and an async
    handler coroutine.  The registry converts registrations to the
    OpenAI function-calling spec format and dispatches incoming tool calls.
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._load_locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: ToolHandler,
        parallel: bool | None = None,
        *,
        is_mutating: bool = True,
        supports_parallel: bool | None = None,
        requires_network_approval: bool = False,
        emits_exec_events: bool = False,
        expose_to_model: bool = True,
        discoverable: bool = True,
        deferred: bool = False,
        source: str = "core",
        keywords: list[str] | None = None,
        loader: ToolLoader | None = None,
    ) -> None:
        """Register (or overwrite) a tool."""
        self._validate_registration(name=name, description=description, input_schema=input_schema)
        resolved_parallel = (
            supports_parallel
            if supports_parallel is not None
            else (parallel if parallel is not None else False)
        )
        self._tools[name] = RegisteredTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            is_mutating=is_mutating,
            supports_parallel=bool(resolved_parallel),
            requires_network_approval=requires_network_approval,
            emits_exec_events=emits_exec_events,
            expose_to_model=expose_to_model,
            discoverable=discoverable,
            deferred=deferred,
            source=source,
            keywords=list(keywords or []),
            loader=loader,
        )
        if name not in self._load_locks:
            self._load_locks[name] = asyncio.Lock()

    def _validate_registration(self, *, name: str, description: str, input_schema: dict) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("tool name must be a non-empty string")
        if len(name) > 128:
            raise ValueError("tool name too long (max 128 chars)")
        if not re.match(r"^[A-Za-z][A-Za-z0-9_.:-]*$", name):
            raise ValueError(
                "invalid tool name; use [A-Za-z][A-Za-z0-9_.:-]*"
            )
        if not isinstance(description, str):
            raise ValueError("tool description must be a string")
        if len(description) > 4000:
            raise ValueError("tool description too long (max 4000 chars)")
        if not isinstance(input_schema, dict):
            raise ValueError("tool input_schema must be a JSON object")
        try:
            schema_json = json.dumps(input_schema, ensure_ascii=True)
        except Exception as exc:
            raise ValueError(f"tool input_schema is not JSON serializable: {exc}") from exc
        if len(schema_json) > 64_000:
            raise ValueError("tool input_schema too large (max 64k JSON chars)")

    def unregister(self, name: str) -> None:
        """Remove a tool by name (no-op if not registered)."""
        self._tools.pop(name, None)
        self._load_locks.pop(name, None)

    def unregister_by_source(self, source: str) -> int:
        """Remove all tools with the given source tag. Returns count removed."""
        to_remove = [name for name, t in self._tools.items() if t.source == source]
        for name in to_remove:
            self._tools.pop(name, None)
            self._load_locks.pop(name, None)
        return len(to_remove)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_tool_specs(self) -> list[dict]:
        """
        Return tool specs in the OpenAI Responses API format (flat, not nested
        under "function" like Chat Completions)::

            [
                {
                    "type": "function",
                    "name": "...",
                    "description": "...",
                    "parameters": {...}
                },
                ...
            ]
        """
        return [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            }
            for t in self._tools.values()
            if t.expose_to_model
        ]

    def has_tool(self, name: str) -> bool:
        """Return True if *name* is currently registered."""
        return name in self._tools

    def list_tools(self) -> list[str]:
        """Return the names of all registered tools."""
        return list(self._tools.keys())

    def get_tool(self, name: str) -> Optional[RegisteredTool]:
        """Return the RegisteredTool for *name*, or None."""
        return self._tools.get(name)

    def get_tool_capabilities(self, name: str) -> RegisteredTool:
        """
        Return tool metadata used by orchestration logic.

        Unknown tools are treated conservatively as mutating + sequential.
        """
        tool = self._tools.get(name)
        if tool is not None:
            return tool
        return RegisteredTool(
            name=name,
            description="",
            input_schema={},
            handler=_unknown_tool_handler,
            is_mutating=True,
            supports_parallel=False,
            requires_network_approval=False,
            emits_exec_events=False,
            expose_to_model=False,
            discoverable=False,
            deferred=False,
            source="unknown",
            keywords=[],
        )

    def enable_tools(self, names: list[str], *, expose_to_model: bool = True) -> list[str]:
        enabled: list[str] = []
        for name in names:
            tool = self._tools.get(name)
            if tool is None:
                continue
            tool.expose_to_model = expose_to_model
            enabled.append(name)
        return enabled

    def list_tool_descriptors(self, *, include_hidden: bool = True) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for t in self._tools.values():
            if not include_hidden and not t.expose_to_model:
                continue
            out.append({
                "name": t.name,
                "description": t.description,
                "source": t.source,
                "is_mutating": t.is_mutating,
                "supports_parallel": t.supports_parallel,
                "requires_network_approval": t.requires_network_approval,
                "expose_to_model": t.expose_to_model,
                "discoverable": t.discoverable,
                "deferred": t.deferred,
                "keywords": list(t.keywords or []),
            })
        return sorted(out, key=lambda x: x["name"])

    def search_tools(
        self,
        *,
        query: str,
        limit: int = 20,
        include_hidden: bool = True,
        sources: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        q_tokens = [tok for tok in re.split(r"[^a-z0-9_]+", q) if tok]
        allowed_sources = {s.strip().lower() for s in (sources or []) if s and s.strip()}
        rows = self.list_tool_descriptors(include_hidden=include_hidden)
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            if not row.get("discoverable", True):
                continue
            src = str(row.get("source", "")).lower()
            if allowed_sources and src not in allowed_sources:
                continue
            name = str(row.get("name", "")).lower()
            desc = str(row.get("description", "")).lower()
            keywords = " ".join(str(k) for k in (row.get("keywords") or [])).lower()
            source = str(row.get("source", "")).lower()
            haystack = " ".join([name, desc, keywords, source])
            if not q:
                score = 1
            else:
                if q not in haystack and not all(tok in haystack for tok in q_tokens):
                    continue
                score = 0
                if name == q:
                    score += 100
                elif name.startswith(q):
                    score += 60
                elif q in name:
                    score += 35

                if q in keywords:
                    score += 30
                if q in desc:
                    score += 20
                if q in source:
                    score += 10

                # Token scoring helps discovery for multi-word queries.
                for tok in q_tokens:
                    if name.startswith(tok):
                        score += 8
                    elif tok in name:
                        score += 5
                    if tok in keywords:
                        score += 4
                    if tok in desc:
                        score += 2

                if row.get("deferred"):
                    score += 1
            scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], item[1]["name"]))
        return [row for _score, row in scored[: max(1, min(limit, 200))]]

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, name: str, tool_input: dict, context: Any) -> str:
        """
        Invoke the handler for *name* with *tool_input* and *context*.

        Returns the string result of the handler, or a formatted error string
        if the tool is unknown or the handler raises.
        """
        await self.ensure_tool_loaded(name)
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'"
        try:
            result = await tool.handler(tool_input, context)
            return result if isinstance(result, str) else str(result)
        except Exception as exc:
            return f"Error executing tool '{name}': {exc}"

    async def ensure_tool_loaded(self, name: str) -> bool:
        tool = self._tools.get(name)
        if tool is None:
            return False
        if not tool.deferred or tool.loader is None:
            return True

        lock = self._load_locks.setdefault(name, asyncio.Lock())
        async with lock:
            latest = self._tools.get(name)
            if latest is None:
                return False
            if not latest.deferred or latest.loader is None:
                return True
            loader = latest.loader
            loaded_handler = loader()
            if asyncio.iscoroutine(loaded_handler):
                loaded_handler = await loaded_handler
            if loaded_handler is None:
                return False
            latest.handler = loaded_handler
            latest.deferred = False
            latest.loader = None
            return True


async def _unknown_tool_handler(_tool_input: dict, _context: Any) -> str:
    return "Error: unknown tool"
