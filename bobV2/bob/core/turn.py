from __future__ import annotations
import asyncio
import uuid
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bob.core.session import BobSession

from bob.protocol.ops import UserTurnOp
from bob.protocol.events import (
    Event,
    TurnStartedEvent,
    TurnEndedEvent,
    TurnInterruptedEvent,
    TextDeltaEvent,
    TextFinalEvent,
    ReasoningDeltaEvent,
    ToolCallStartedEvent,
    ToolCallCompletedEvent,
    ExecStartedEvent,
    ExecOutputEvent,
    ExecCompletedEvent,
    ExecApprovalRequestedEvent,
    ExecApprovalResolvedEvent,
    TokenBudgetEvent,
    ErrorEvent,
)
from bob.client.openai_client import (
    TextDeltaEvent as ClientTextDelta,
    ToolCallEvent as ClientToolCall,
    CompletedEvent as ClientCompleted,
    StreamErrorEvent as ClientStreamError,
    ReasoningDeltaEvent as ClientReasoningDelta,
)
from bob.protocol.config_types import AskForApproval, ReviewDecision, ExecCommandSource, ExecCommandStatus

# ---------------------------------------------------------------------------
# Approval policy helpers
# ---------------------------------------------------------------------------

TRUSTED_COMMANDS: frozenset[str] = frozenset([
    # Unix read-only
    "ls", "cat", "pwd", "echo", "which", "file",
    "head", "tail", "wc", "sort", "uniq", "cut", "tr",
    "grep", "rg", "ag", "fd", "find",
    # Windows read-only (cmd + PowerShell)
    "dir", "more", "type", "tree", "where",
    "Get-ChildItem", "Get-Content", "Get-Location",
    "Get-Item", "Get-ItemProperty", "Get-Process",
    "Select-String", "Measure-Object",
    # Git read-only
    "git status", "git log", "git diff", "git branch",
    "git show", "git fetch", "git remote",
    # Version/info checks
    "python --version", "python3 --version", "node --version",
    "pip list", "pip show", "pip freeze",
    "npm list", "npm --version",
])


def needs_approval(
    command: list[str],
    policy: AskForApproval,
    session_approved: set[str],
    trusted_patterns: list = None,
) -> bool:
    """Return True if this command requires user approval before execution."""
    if policy == AskForApproval.NEVER:
        return False
    if policy == AskForApproval.ON_REQUEST:
        # ON_REQUEST means: ask unless the user pre-approved
        return True
    if policy == AskForApproval.ON_FAILURE:
        # Don't ask upfront; re-run with approval on non-zero exit
        return False
    if policy == AskForApproval.UNLESS_TRUSTED:
        cmd0 = command[0] if command else ""
        cmd2 = " ".join(command[:2])
        # Check built-in trusted set
        if cmd0 in TRUSTED_COMMANDS or cmd2 in TRUSTED_COMMANDS:
            return False
        # Check session-approved commands
        key = " ".join(command[:2])
        if key in session_approved:
            return False
        # Check configured trusted command patterns
        if trusted_patterns:
            import fnmatch
            cmd_str = " ".join(command)
            for rule in trusted_patterns:
                pattern = getattr(rule, "pattern", str(rule))
                use_regex = getattr(rule, "use_regex", False)
                if use_regex:
                    import re
                    try:
                        if re.search(pattern, cmd_str):
                            return False
                    except re.error:
                        pass
                else:
                    if fnmatch.fnmatch(cmd_str, pattern):
                        return False
        return True
    return True


# ---------------------------------------------------------------------------
# Turn runner
# ---------------------------------------------------------------------------

async def run_turn(
    session: "BobSession",
    sub_id: str,
    op: UserTurnOp,
    cancel_event: asyncio.Event,
) -> None:
    """Execute one complete agent turn, including all tool call iterations."""
    turn_id = str(uuid.uuid4())
    session_approved_commands: set[str] = set()

    async def emit(msg) -> None:
        await session._emit(Event(id=sub_id, msg=msg))

    # ------------------------------------------------------------------ #
    # Turn started                                                        #
    # ------------------------------------------------------------------ #
    await emit(TurnStartedEvent(type="turn_started", turn_id=turn_id))

    if session._recorder:
        await session._recorder.write({
            "type": "turn_context",
            "turn_id": turn_id,
            "model": session.config.model,
            "cwd": str(session.cwd),
        })

    # ------------------------------------------------------------------ #
    # Build user message content and add to history                      #
    # ------------------------------------------------------------------ #
    user_content: list[dict] = []
    for item in op.items:
        if item.type == "text":
            user_content.append({"type": "input_text", "text": item.text})
        elif item.type == "image":
            import base64
            try:
                data = item.path.read_bytes()
                b64 = base64.b64encode(data).decode()
                suffix = item.path.suffix.lower().lstrip(".")
                mime = f"image/{suffix if suffix in ('png', 'jpg', 'jpeg', 'gif', 'webp') else 'png'}"
                user_content.append({
                    "type": "input_image",
                    "image_url": f"data:{mime};base64,{b64}",
                })
            except OSError:
                pass

    # Optionally prepend a developer message override for this turn
    if op.developer_message_override:
        user_content.insert(0, {
            "type": "input_text",
            "text": f"[System note: {op.developer_message_override}]\n",
        })

    if not user_content:
        user_content = [{"type": "input_text", "text": ""}]

    user_msg = {"role": "user", "content": user_content}
    session.context_manager.record_items([user_msg])

    if session._recorder:
        await session._recorder.write({
            "type": "user_message",
            "turn_id": turn_id,
            "items": user_content,
        })

    # ------------------------------------------------------------------ #
    # Attach per-turn callbacks onto the session for tool context access  #
    # ------------------------------------------------------------------ #
    async def on_output_delta(data: str, stream: str) -> None:
        # Streaming shell output from within the turn reaches here; we emit
        # it via ExecOutputEvent but need the call_id — shell tool directly
        # uses the context callback it receives.
        pass

    async def on_plan_update(args) -> None:
        from bob.protocol.events import PlanUpdatedEvent
        from bob.protocol.plan_types import PlanItemArg
        # args may be a list of dicts or PlanItemArg objects
        if isinstance(args, list):
            plan = [PlanItemArg(**a) if isinstance(a, dict) else a for a in args]
        else:
            plan = []
        await emit(PlanUpdatedEvent(
            type="plan_updated",
            explanation=None,
            plan=plan,
        ))

    session._current_on_output_delta = on_output_delta
    session._current_on_plan_update = on_plan_update

    # ------------------------------------------------------------------ #
    # Agentic tool-call loop                                              #
    # ------------------------------------------------------------------ #
    max_iterations = 50
    iteration = 0
    total_input_tokens = 0
    total_output_tokens = 0

    try:
        while iteration < max_iterations:
            iteration += 1

            if cancel_event.is_set():
                await emit(TurnInterruptedEvent(
                    type="turn_interrupted", turn_id=turn_id, graceful=True
                ))
                return

            current_history = session.context_manager.raw_items()
            tool_specs = session.tool_registry.get_tool_specs()

            text_parts: list[str] = []
            tool_calls: list[ClientToolCall] = []
            iter_input_tokens = 0
            iter_output_tokens = 0

            # ----------------------------------------------------------
            # Stream from model
            # ----------------------------------------------------------
            try:
                async for ev in session.client.stream_turn(
                    input=current_history,
                    instructions=session._system_prompt or "",
                    tools=tool_specs,
                ):
                    if cancel_event.is_set():
                        break

                    if isinstance(ev, ClientTextDelta):
                        text_parts.append(ev.delta)
                        await emit(TextDeltaEvent(type="text_delta", delta=ev.delta))

                    elif isinstance(ev, ClientReasoningDelta):
                        await emit(ReasoningDeltaEvent(
                            type="reasoning_delta", delta=ev.delta
                        ))

                    elif isinstance(ev, ClientToolCall):
                        tool_calls.append(ev)

                    elif isinstance(ev, ClientCompleted):
                        iter_input_tokens = ev.input_tokens
                        iter_output_tokens = ev.output_tokens
                        total_input_tokens += ev.input_tokens
                        total_output_tokens += ev.output_tokens

                    elif isinstance(ev, ClientStreamError):
                        await emit(ErrorEvent(
                            type="error",
                            message=f"Stream error: {ev.message}",
                        ))

            except asyncio.CancelledError:
                await emit(TurnInterruptedEvent(
                    type="turn_interrupted", turn_id=turn_id, graceful=False
                ))
                return
            except Exception as exc:
                await emit(ErrorEvent(type="error", message=str(exc)))
                await emit(TurnEndedEvent(
                    type="turn_ended",
                    turn_id=turn_id,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                ))
                return

            if cancel_event.is_set():
                await emit(TurnInterruptedEvent(
                    type="turn_interrupted", turn_id=turn_id, graceful=True
                ))
                return

            # ----------------------------------------------------------
            # Emit token budget update
            # ----------------------------------------------------------
            if iter_input_tokens or iter_output_tokens:
                used = total_input_tokens + total_output_tokens
                budget = 200_000
                await emit(TokenBudgetEvent(
                    type="token_budget",
                    used_tokens=used,
                    budget_tokens=budget,
                    fraction_used=min(1.0, used / budget),
                ))

            # ----------------------------------------------------------
            # Finalise text
            # ----------------------------------------------------------
            full_text = "".join(text_parts)
            if full_text:
                await emit(TextFinalEvent(type="text_final", text=full_text))

            # ----------------------------------------------------------
            # Build history items in Responses API format:
            #   - text → {"role":"assistant","content":[{"type":"output_text",...}]}
            #   - each tool call → top-level {"type":"function_call",...}
            # ----------------------------------------------------------
            import json as _json

            history_items: list[dict] = []
            if full_text:
                history_items.append({
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": full_text}],
                })
            for tc in tool_calls:
                history_items.append({
                    "type": "function_call",
                    "call_id": tc.id,
                    "name": tc.name,
                    "arguments": _json.dumps(tc.input),
                })

            if history_items:
                session.context_manager.record_items(history_items)
                if session._recorder:
                    for item in history_items:
                        await session._recorder.write({
                            "type": "response_item",
                            "turn_id": turn_id,
                            "item": item,
                        })

            # ----------------------------------------------------------
            # If no tool calls, turn is complete
            # ----------------------------------------------------------
            if not tool_calls:
                break

            # ----------------------------------------------------------
            # Execute tool calls and collect results
            # ----------------------------------------------------------
            tool_results: list[dict] = []

            for tc in tool_calls:
                if cancel_event.is_set():
                    break

                call_id = tc.id
                tool_name = tc.name
                result_text = ""

                await emit(ToolCallStartedEvent(
                    type="tool_call_started",
                    tool_call_id=call_id,
                    tool_name=tool_name,
                    tool_input=tc.input,
                ))

                # -------------------------------------------------------
                # Shell tool (and aliases)
                # -------------------------------------------------------
                if tool_name in ("shell", "local_shell", "bash"):
                    raw_cmd = tc.input.get("command", [])
                    # Model sometimes sends command as a string instead of array
                    if isinstance(raw_cmd, str):
                        command: list[str] = raw_cmd.split()
                    else:
                        command: list[str] = list(raw_cmd)

                    exec_cwd = session.cwd
                    workdir = tc.input.get("workdir")
                    if workdir:
                        p = Path(workdir)
                        exec_cwd = p if p.is_absolute() else session.cwd / p

                    # -------------------------------------------------------
                    # apply_patch: route to Python impl, never subprocess
                    # -------------------------------------------------------
                    if command and command[0] == "apply_patch":
                        patch_text = command[1] if len(command) > 1 else ""
                        if not patch_text:
                            result_text = "Error: apply_patch requires patch content"
                        else:
                            from bob.tools.apply_patch import apply_patch_command
                            await emit(ExecStartedEvent(
                                type="exec_started",
                                tool_call_id=call_id,
                                command=command,
                                cwd=str(exec_cwd),
                                source=ExecCommandSource.AGENT,
                                sandbox_mode=session.sandbox_policy.mode,
                            ))
                            result_text = await apply_patch_command(patch_text, exec_cwd)
                            exit_code = 0 if not result_text.startswith("Error") else 1
                            await emit(ExecCompletedEvent(
                                type="exec_completed",
                                tool_call_id=call_id,
                                exit_code=exit_code,
                                status=ExecCommandStatus.COMPLETED if exit_code == 0 else ExecCommandStatus.FAILED,
                                duration_ms=0,
                            ))
                        await emit(ToolCallCompletedEvent(
                            type="tool_call_completed",
                            tool_call_id=call_id,
                            tool_name=tool_name,
                            output=result_text,
                        ))
                        tool_results.append({
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": result_text,
                        })
                        continue

                    approval_needed = needs_approval(
                        command,
                        session.config.ask_for_approval,
                        session_approved_commands,
                        trusted_patterns=session.config.trusted_commands,
                    )

                    if approval_needed:
                        await emit(ExecApprovalRequestedEvent(
                            type="exec_approval_requested",
                            tool_call_id=call_id,
                            command=command,
                            cwd=str(exec_cwd),
                            reason="Command requires approval per policy",
                            alternatives=[],
                        ))
                        decision = await session.get_approval(call_id)
                        await emit(ExecApprovalResolvedEvent(
                            type="exec_approval_resolved",
                            tool_call_id=call_id,
                            decision=decision,
                        ))
                        if decision == ReviewDecision.ABORT:
                            await emit(TurnInterruptedEvent(
                                type="turn_interrupted", turn_id=turn_id, graceful=True
                            ))
                            return
                        if decision == ReviewDecision.DENIED:
                            result_text = "Command denied by user."
                            await emit(ToolCallCompletedEvent(
                                type="tool_call_completed",
                                tool_call_id=call_id,
                                tool_name=tool_name,
                                output=result_text,
                            ))
                            tool_results.append({
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": result_text,
                            })
                            continue
                        if decision == ReviewDecision.APPROVED_FOR_SESSION:
                            key = " ".join(command[:2])
                            session_approved_commands.add(key)

                    # Emit exec started
                    await emit(ExecStartedEvent(
                        type="exec_started",
                        tool_call_id=call_id,
                        command=command,
                        cwd=str(exec_cwd),
                        source=ExecCommandSource.AGENT,
                        sandbox_mode=session.sandbox_policy.mode,
                    ))

                    # Execute
                    from bob.core.exec import execute_command

                    async def on_delta(data: str, stream: str) -> None:
                        await emit(ExecOutputEvent(
                            type="exec_output",
                            tool_call_id=call_id,
                            stream=stream,
                            data=data,
                        ))

                    timeout_ms: int = tc.input.get("timeout", 10_000)
                    exec_result = await execute_command(
                        command=command,
                        cwd=exec_cwd,
                        sandbox=session._sandbox_runner,
                        cancel_event=cancel_event,
                        on_output_delta=on_delta,
                        timeout_ms=timeout_ms,
                    )

                    status = (
                        ExecCommandStatus.COMPLETED
                        if exec_result.exit_code == 0
                        else ExecCommandStatus.FAILED
                    )
                    await emit(ExecCompletedEvent(
                        type="exec_completed",
                        tool_call_id=call_id,
                        exit_code=exec_result.exit_code,
                        status=status,
                        duration_ms=exec_result.duration_ms,
                    ))

                    result_text = exec_result.aggregated_output or exec_result.stdout
                    if exec_result.timed_out:
                        result_text = f"[Command timed out]\n{result_text}"
                    elif exec_result.exit_code != 0:
                        if result_text.strip():
                            result_text += f"\n[Exit code: {exec_result.exit_code}]"
                        else:
                            result_text = f"[Exit code: {exec_result.exit_code}]"

                    # ON_FAILURE policy: re-request approval after failure
                    if (
                        exec_result.exit_code != 0
                        and session.config.ask_for_approval == AskForApproval.ON_FAILURE
                    ):
                        await emit(ExecApprovalRequestedEvent(
                            type="exec_approval_requested",
                            tool_call_id=call_id,
                            command=command,
                            cwd=str(exec_cwd),
                            reason=f"Command failed with exit code {exec_result.exit_code}",
                            alternatives=[],
                        ))

                # -------------------------------------------------------
                # All other registered tools
                # -------------------------------------------------------
                else:
                    from bob.core.session import ToolContext
                    ctx = ToolContext(session)
                    ctx.on_output_delta = on_output_delta
                    ctx.on_plan_update = on_plan_update

                    import time
                    t0 = time.monotonic()
                    try:
                        result_text = await session.tool_registry.dispatch(
                            tool_name, tc.input, ctx
                        )
                    except Exception as exc:
                        result_text = f"Error: {exc}"
                    duration_ms = int((time.monotonic() - t0) * 1000)

                    await emit(ToolCallCompletedEvent(
                        type="tool_call_completed",
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        output=result_text,
                        duration_ms=duration_ms,
                    ))

                # Record tool result for history
                if tool_name not in ("shell", "local_shell", "bash"):
                    pass  # already emitted ToolCallCompleted above

                tool_results.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": result_text,
                })

            # Record tool results into context and continue loop
            if tool_results:
                session.context_manager.record_items(tool_results)
                if session._recorder:
                    await session._recorder.write({
                        "type": "tool_results",
                        "turn_id": turn_id,
                        "results": tool_results,
                    })

        # ------------------------------------------------------------------ #
        # Turn ended normally                                                 #
        # ------------------------------------------------------------------ #
        await emit(TurnEndedEvent(
            type="turn_ended",
            turn_id=turn_id,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        ))

        if session._recorder:
            await session._recorder.write({
                "type": "turn_ended",
                "turn_id": turn_id,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
            })

    except asyncio.CancelledError:
        await emit(TurnInterruptedEvent(
            type="turn_interrupted", turn_id=turn_id, graceful=False
        ))
        raise
