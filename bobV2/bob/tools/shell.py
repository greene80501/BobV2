from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from bob.core.exec import execute_command, DEFAULT_TIMEOUT_MS
from bob.tools.path_utils import resolve_tool_path

SHELL_TOOL_DESCRIPTION = (
    "Execute a shell command in the sandbox. Use this for running programs, "
    "reading files, listing directories, searching, git operations, and all "
    "other terminal operations. The command runs in the current working directory. "
    "On Windows use PowerShell/cmd syntax (e.g. Get-Content, dir, where). "
    "To write or replace files use apply_patch instead of shell redirection."
)

SHELL_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Command and arguments as an array, e.g. ['ls', '-la'] "
                "or ['apply_patch', '*** Begin Patch...']"
            ),
        },
        "workdir": {
            "type": "string",
            "description": (
                "Optional working directory override (relative to cwd or absolute)."
            ),
        },
        "timeout": {
            "type": "integer",
            "description": f"Timeout in milliseconds (default: {DEFAULT_TIMEOUT_MS}).",
        },
    },
    "required": ["command"],
}


async def shell_handler(tool_input: dict, context: Any) -> str:
    """
    Handle a ``shell`` tool call from the agent.

    Special case: if the first element of *command* is ``apply_patch``, the
    call is routed to our Python patch applier instead of being executed in a
    subprocess.

    *context* must expose:
      - ``context.cwd``               – :class:`pathlib.Path`
      - ``context.sandbox``           – :class:`bob.sandbox.base.SandboxRunner`
      - ``context.cancel_event``      – :class:`asyncio.Event` or ``None``
      - ``context.on_output_delta``   – async callback ``(data, stream) -> None`` or ``None``
    """
    command: list[str] = tool_input.get("command", [])
    if not command:
        return "Error: empty command"

    # ------------------------------------------------------------------ #
    # Special case: apply_patch routed to Python implementation           #
    # ------------------------------------------------------------------ #
    if command[0] == "apply_patch":
        from bob.tools.apply_patch import apply_patch_command

        if len(command) < 2:
            return "Error: apply_patch requires patch content as second argument"
        return await apply_patch_command(command[1], context.cwd)

    # ------------------------------------------------------------------ #
    # Resolve working directory                                           #
    # ------------------------------------------------------------------ #
    workdir_str: Optional[str] = tool_input.get("workdir")
    if workdir_str:
        cwd = resolve_tool_path(workdir_str, context.cwd)
    else:
        cwd = context.cwd

    timeout_ms: int = tool_input.get("timeout", DEFAULT_TIMEOUT_MS)

    # ------------------------------------------------------------------ #
    # Output streaming callback                                           #
    # ------------------------------------------------------------------ #
    async def on_delta(data: str, stream: str) -> None:
        if context.on_output_delta is not None:
            await context.on_output_delta(data, stream)

    # ------------------------------------------------------------------ #
    # Execute                                                             #
    # ------------------------------------------------------------------ #
    result = await execute_command(
        command=command,
        cwd=cwd,
        sandbox=context.sandbox,
        timeout_ms=timeout_ms,
        cancel_event=getattr(context, "cancel_event", None),
        on_output_delta=on_delta,
    )

    # ------------------------------------------------------------------ #
    # Format output                                                       #
    # ------------------------------------------------------------------ #
    output = result.aggregated_output or result.stdout

    if result.timed_out:
        output = f"[Command timed out after {timeout_ms}ms]\n{output}"
    elif result.exit_code != 0:
        if output.strip():
            output = output + f"\n[Exit code: {result.exit_code}]"
        else:
            output = f"[Exit code: {result.exit_code}]"

    return output
