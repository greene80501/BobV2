from __future__ import annotations

import json
import re

from bob.app_server.routes._utils import parse_params
from bob.protocol.ops import DynamicToolResponseOp
from bob.protocol.v1.requests import (
    DynamicToolsEnableParams,
    DynamicToolsListParams,
    DynamicToolsRegisterParams,
    DynamicToolsRespondParams,
    DynamicToolsSearchParams,
)

_DYNAMIC_TOOL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_MAX_DYNAMIC_TOOLS_PER_REGISTER = 128
_MAX_DYNAMIC_RESULT_CHARS = 100_000


def _validate_dynamic_spec(spec) -> None:
    if not _DYNAMIC_TOOL_NAME_RE.match(spec.name):
        raise ValueError(
            f"Invalid tool name '{spec.name}'. Expected pattern [A-Za-z][A-Za-z0-9_.:-]*"
        )
    if len(spec.description) > 4000:
        raise ValueError(f"Tool '{spec.name}' description too long (max 4000 chars)")
    if spec.timeout_seconds <= 0 or spec.timeout_seconds > 900:
        raise ValueError(f"Tool '{spec.name}' timeout_seconds must be in range (0, 900]")
    if spec.max_retries < 0 or spec.max_retries > 5:
        raise ValueError(f"Tool '{spec.name}' max_retries must be between 0 and 5")
    if spec.max_output_chars < 256 or spec.max_output_chars > _MAX_DYNAMIC_RESULT_CHARS:
        raise ValueError(
            f"Tool '{spec.name}' max_output_chars must be between 256 and {_MAX_DYNAMIC_RESULT_CHARS}"
        )
    try:
        schema_json = json.dumps(spec.input_schema, ensure_ascii=True)
    except Exception as exc:
        raise ValueError(f"Tool '{spec.name}' input_schema is not JSON serializable: {exc}") from exc
    if len(schema_json) > 64_000:
        raise ValueError(f"Tool '{spec.name}' input_schema too large (max 64k chars)")


def register(router) -> None:
    async def dynamic_tools_register(ctx, params: dict):
        p = parse_params(DynamicToolsRegisterParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)

        if len(p.tools) > _MAX_DYNAMIC_TOOLS_PER_REGISTER:
            return {
                "error": (
                    f"Too many tools in one register call: {len(p.tools)} "
                    f"(max {_MAX_DYNAMIC_TOOLS_PER_REGISTER})"
                )
            }

        registered: list[str] = []
        for spec in p.tools:
            try:
                _validate_dynamic_spec(spec)
            except ValueError as exc:
                return {"error": str(exc)}

            tool_name = spec.name

            async def _dynamic_handler(
                tool_input: dict,
                tool_context,
                _name: str = tool_name,
                _timeout_seconds: float = spec.timeout_seconds,
                _max_retries: int = spec.max_retries,
                _max_output_chars: int = spec.max_output_chars,
            ) -> str:
                call_id = getattr(tool_context, "current_tool_call_id", None)
                if not call_id:
                    import uuid

                    call_id = str(uuid.uuid4())
                return await tool_context._session.request_dynamic_tool(
                    tool_call_id=call_id,
                    tool_name=_name,
                    tool_input=tool_input,
                    timeout_seconds=_timeout_seconds,
                    max_retries=_max_retries,
                    max_output_chars=_max_output_chars,
                )

            thread.session.tool_registry.register(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
                handler=_dynamic_handler,
                is_mutating=spec.is_mutating,
                supports_parallel=spec.supports_parallel,
                requires_network_approval=spec.requires_network_approval,
                expose_to_model=spec.expose_to_model,
                discoverable=spec.discoverable,
                deferred=spec.deferred,
                source=spec.source,
                keywords=spec.keywords,
            )
            registered.append(spec.name)

        await ctx.event_bus.publish(
            [f"thread:{p.thread_id}"],
            {
                "thread_id": p.thread_id,
                "event": {
                    "type": "dynamic_tools.registered",
                    "tools": registered,
                },
            },
        )
        return {"registered": registered}

    async def dynamic_tools_list(ctx, params: dict):
        p = parse_params(DynamicToolsListParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        rows = thread.session.tool_registry.list_tool_descriptors(include_hidden=p.include_hidden)
        if p.source:
            wanted = p.source.strip().lower()
            rows = [r for r in rows if str(r.get("source", "")).lower() == wanted]
        return {"tools": rows}

    async def dynamic_tools_search(ctx, params: dict):
        p = parse_params(DynamicToolsSearchParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)

        rows = thread.session.tool_registry.search_tools(
            query=p.query,
            limit=p.limit,
            include_hidden=p.include_hidden,
            sources=p.sources or None,
        )

        enabled: list[str] = []
        if p.auto_enable:
            to_enable = [r["name"] for r in rows if not bool(r.get("expose_to_model", False))]
            enabled = thread.session.tool_registry.enable_tools(to_enable)
            for name in enabled:
                await thread.session.tool_registry.ensure_tool_loaded(name)

        await ctx.event_bus.publish(
            [f"thread:{p.thread_id}"],
            {
                "thread_id": p.thread_id,
                "event": {
                    "type": "dynamic_tools.search",
                    "query": p.query,
                    "count": len(rows),
                    "enabled": enabled,
                },
            },
        )
        return {"tools": rows, "enabled": enabled}

    async def dynamic_tools_enable(ctx, params: dict):
        p = parse_params(DynamicToolsEnableParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        enabled = thread.session.tool_registry.enable_tools(
            p.tool_names,
            expose_to_model=p.expose_to_model,
        )
        for name in enabled:
            await thread.session.tool_registry.ensure_tool_loaded(name)
        await ctx.event_bus.publish(
            [f"thread:{p.thread_id}"],
            {
                "thread_id": p.thread_id,
                "event": {
                    "type": "dynamic_tools.enabled",
                    "tools": enabled,
                    "expose_to_model": p.expose_to_model,
                },
            },
        )
        return {"enabled": enabled, "expose_to_model": p.expose_to_model}

    async def dynamic_tools_respond(ctx, params: dict):
        p = parse_params(DynamicToolsRespondParams, params)
        if len((p.tool_call_id or "").strip()) == 0:
            return {"error": "tool_call_id is required"}
        try:
            encoded = json.dumps(p.result, ensure_ascii=False, default=str)
            if len(encoded) > _MAX_DYNAMIC_RESULT_CHARS:
                return {
                    "error": (
                        f"dynamic tool result too large ({len(encoded)} chars); "
                        f"max {_MAX_DYNAMIC_RESULT_CHARS}"
                    )
                }
        except Exception as exc:
            return {"error": f"dynamic tool result is not JSON serializable: {exc}"}

        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        await thread.session.submit(
            DynamicToolResponseOp(
                type="dynamic_tool_response",
                tool_call_id=p.tool_call_id,
                result=p.result,
            )
        )
        await ctx.event_bus.publish(
            [f"thread:{p.thread_id}"],
            {
                "thread_id": p.thread_id,
                "event": {
                    "type": "dynamic_tools.responded",
                    "tool_call_id": p.tool_call_id,
                },
            },
        )
        return {"status": "ok", "tool_call_id": p.tool_call_id}

    router.add("dynamic_tools.register", dynamic_tools_register)
    router.add("dynamic_tools.list", dynamic_tools_list)
    router.add("dynamic_tools.search", dynamic_tools_search)
    router.add("dynamic_tools.enable", dynamic_tools_enable)
    router.add("dynamic_tools.respond", dynamic_tools_respond)
