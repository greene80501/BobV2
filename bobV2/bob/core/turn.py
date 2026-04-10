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
from bob.llm.client import (
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


def _canonicalize_command(command: list[str]) -> list[str]:
    """Strip shell wrapper tokens to get the real command for trust matching.

    Handles:
    - cmd /c <real>  /  cmd.exe /c <real>
    - powershell -Command <real>  /  pwsh -Command <real>
    - bash -c <real>  /  sh -c <real>
    - Strips leading ./ and resolves obvious path prefixes on the first token.
    """
    if not command:
        return command

    result = list(command)

    # Unwrap cmd /c and PowerShell -Command wrappers (case-insensitive)
    exe = result[0].lower().rstrip(".exe")
    if exe in ("cmd", "powershell", "pwsh"):
        # Find -c / /c / -Command flag and take everything after it
        for i, tok in enumerate(result[1:], 1):
            if tok.lower() in ("/c", "-c", "-command"):
                remainder = result[i + 1:]
                if remainder:
                    # remainder may be a single string or already split tokens
                    if len(remainder) == 1:
                        import shlex
                        try:
                            result = shlex.split(remainder[0])
                        except ValueError:
                            result = remainder
                    else:
                        result = remainder
                    exe = result[0].lower().rstrip(".exe")
                break

    # Unwrap bash/sh -c wrappers
    if exe in ("bash", "sh", "zsh", "fish") and len(result) >= 3 and result[1] == "-c":
        import shlex
        try:
            result = shlex.split(result[2])
        except ValueError:
            result = [result[2]]

    # Strip leading ./ from the command name
    if result and result[0].startswith("./"):
        result = [result[0][2:]] + result[1:]

    return result


import os as _os
from pathlib import Path as _Path
import logging as _logging
_escalation_logger = _logging.getLogger("bob.security.escalation")

# ---------------------------------------------------------------------------
# File-diff helpers for turn tracking
# ---------------------------------------------------------------------------

_SNAPSHOT_SKIP = frozenset([
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    ".bob", ".mypy_cache", ".ruff_cache", ".pytest_cache",
])


def _snapshot_dir(cwd) -> dict[str, tuple[float, int]]:
    """Return {relative_path: (mtime, size)} for all regular files in *cwd*.

    Limits to 5 000 files and skips common noise directories to stay fast.
    """
    root = _Path(cwd)
    snapshot: dict[str, tuple[float, int]] = {}
    try:
        for dirpath, dirnames, filenames in _os.walk(root):
            # Prune noise directories in-place
            dirnames[:] = [d for d in dirnames if d not in _SNAPSHOT_SKIP]
            for fname in filenames:
                full = _Path(dirpath) / fname
                try:
                    st = full.stat()
                    rel = str(full.relative_to(root))
                    snapshot[rel] = (st.st_mtime, st.st_size)
                except OSError:
                    pass
            if len(snapshot) >= 5_000:
                break
    except OSError:
        pass
    return snapshot


def _diff_snapshot(
    before: dict[str, tuple[float, int]],
    after:  dict[str, tuple[float, int]],
) -> list[str]:
    """Return sorted list of paths that were added, deleted, or modified."""
    changed: list[str] = []
    all_keys = set(before) | set(after)
    for k in all_keys:
        b = before.get(k)
        a = after.get(k)
        if b != a:
            changed.append(k)
    return sorted(changed)

# Patterns that indicate a privilege-escalation or sandbox-escape attempt.
_ESCALATION_TOKENS: frozenset[str] = frozenset([
    "sudo", "su", "doas",
    "chroot", "nsenter", "unshare", "pivot_root",
    "ptrace", "strace", "ltrace",
    "LD_PRELOAD", "LD_LIBRARY_PATH",
    "setuid", "setgid", "setcap",
])

# Dangerous metacharacters in a *trusted* command's arguments
_DANGEROUS_METACHAR_RE = None


def _get_metachar_re():
    global _DANGEROUS_METACHAR_RE
    if _DANGEROUS_METACHAR_RE is None:
        import re
        _DANGEROUS_METACHAR_RE = re.compile(r"[|;&`$]")
    return _DANGEROUS_METACHAR_RE


def detect_escalation(command: list[str]) -> str | None:
    """Return a human-readable reason if the command looks like an escalation attempt.

    Returns None if the command is considered safe.
    """
    if not command:
        return None
    canonical = _canonicalize_command(command)
    cmd0 = canonical[0] if canonical else ""

    # Direct escalation command
    if cmd0 in _ESCALATION_TOKENS:
        _escalation_logger.warning("Escalation attempt blocked: %s", command)
        return f"'{cmd0}' is a privilege-escalation command"

    # LD_PRELOAD / LD_LIBRARY_PATH as environment prefix (e.g. ["LD_PRELOAD=/evil.so", "ls"])
    for tok in canonical:
        for esc in ("LD_PRELOAD=", "LD_LIBRARY_PATH="):
            if tok.startswith(esc):
                _escalation_logger.warning("Escalation attempt blocked (env override): %s", command)
                return f"Environment override '{esc}' is not permitted"

    # Shell metacharacters injected into what looks like a single trusted token
    # e.g. ["ls", "; rm -rf /"]
    meta_re = _get_metachar_re()
    for tok in canonical[1:]:
        if meta_re.search(tok):
            _escalation_logger.warning("Possible metachar injection: %s", command)
            # Don't hard-block — just force approval
            return f"Shell metacharacter in argument '{tok[:40]}'"

    return None


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
        # Canonicalize before any trust checks so wrappers can't bypass approval
        canonical = _canonicalize_command(command)
        cmd0 = canonical[0] if canonical else ""
        cmd2 = " ".join(canonical[:2])
        # Check built-in trusted set
        if cmd0 in TRUSTED_COMMANDS or cmd2 in TRUSTED_COMMANDS:
            return False
        # Check session-approved commands (match on canonical form)
        key = " ".join(canonical[:2])
        if key in session_approved:
            return False
        # Check configured trusted command patterns
        if trusted_patterns:
            import fnmatch
            cmd_str = " ".join(canonical)
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

    # Analytics: begin timing this turn
    if hasattr(session, "analytics") and session.analytics is not None:
        session.analytics.start_turn(session.session_id, turn_id, session.config.model)

    # Snapshot file mtimes/sizes so we can detect what changed this turn
    _file_snapshot_before = _snapshot_dir(session.cwd)

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
    total_cached_input_tokens = 0

    try:
        while iteration < max_iterations:
            iteration += 1

            if cancel_event.is_set():
                await emit(TurnInterruptedEvent(
                    type="turn_interrupted", turn_id=turn_id, graceful=True
                ))
                return

            current_history = session.context_manager.raw_items()

            # Scrub any orphaned function_calls that have no matching output.
            # These are left behind when a turn crashes mid-execution; sending
            # them to the API causes a 400 "No tool output found" error.
            _seen_outputs: set[str] = {
                item["call_id"]
                for item in current_history
                if item.get("type") == "function_call_output"
            }
            _orphaned_ids: set[str] = {
                item["call_id"]
                for item in current_history
                if item.get("type") == "function_call"
                and item.get("call_id") not in _seen_outputs
            }
            if _orphaned_ids:
                patched: list = []
                for item in current_history:
                    patched.append(item)
                    if (
                        item.get("type") == "function_call"
                        and item.get("call_id") in _orphaned_ids
                    ):
                        patched.append({
                            "type": "function_call_output",
                            "call_id": item["call_id"],
                            "output": "[Tool execution was interrupted]",
                        })
                session.context_manager.replace(patched)
                current_history = patched

            tool_specs = session.tool_registry.get_tool_specs()
            # In plan mode: only expose read-only tools
            if getattr(session, "_plan_mode", False):
                _write_tools = {"write_file", "edit_file", "shell", "apply_patch"}
                tool_specs = [s for s in tool_specs if s.get("function", {}).get("name") not in _write_tools]

            text_parts: list[str] = []
            tool_calls: list[ClientToolCall] = []
            iter_input_tokens = 0
            iter_output_tokens = 0

            # ----------------------------------------------------------
            # Stream from model
            # ----------------------------------------------------------
            from bob.llm.compatibility import build_model_request_params

            compatibility, _provider_auth = session.get_model_runtime(session.config.model)
            extra_params = build_model_request_params(session.config, compatibility)

            try:
                async for ev in session.client.stream_turn(
                    input=current_history,
                    instructions=session._system_prompt or "",
                    tools=tool_specs,
                    extra_params=extra_params,
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
                        total_cached_input_tokens += ev.cached_input_tokens

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

            # Classify tools as read-only (safe for parallel) vs write (sequential)
            READ_ONLY_TOOLS = frozenset({
                "read_file", "list_dir", "glob_files", "grep_files",
                "web_fetch", "web_search", "view_image", "notebook_read",
                "task_list", "task_get",  # read-only task tools
            })
            
            # Check if in plan mode and block write tools
            if getattr(session, '_plan_mode', False):
                blocked_calls = [tc for tc in tool_calls if tc.name not in READ_ONLY_TOOLS]
                if blocked_calls:
                    # Block all write tools in plan mode
                    for tc in blocked_calls:
                        await emit(ToolCallStartedEvent(
                            type="tool_call_started",
                            tool_call_id=tc.id,
                            tool_name=tc.name,
                            tool_input=tc.input,
                        ))
                        await emit(ToolCallCompletedEvent(
                            type="tool_call_completed",
                            tool_call_id=tc.id,
                            tool_name=tc.name,
                            output=f"❌ Tool '{tc.name}' blocked in Plan mode. Only read-only tools are available. Use exit_plan_mode to unlock.",
                            duration_ms=0,
                        ))
                        tool_results.append({
                            "type": "function_call_output",
                            "call_id": tc.id,
                            "output": f"❌ Tool '{tc.name}' blocked in Plan mode. Only read-only tools are available. Use exit_plan_mode to unlock.",
                        })
                    # Only process read-only tools
                    tool_calls = [tc for tc in tool_calls if tc.name in READ_ONLY_TOOLS]
                    if not tool_calls:
                        # All tools were blocked, continue to next iteration
                        continue
            
            # Network approval for web tools (must happen sequentially before parallel dispatch)
            _WEB_TOOLS = frozenset({"web_fetch", "web_search"})
            _denied_call_ids: set[str] = set()
            for tc in tool_calls:
                if tc.name not in _WEB_TOOLS:
                    continue
                if tc.name == "web_search":
                    url = f"duckduckgo.com/search?q={tc.input.get('query', '')}"
                    domain = "duckduckgo.com"
                else:
                    url = tc.input.get("url", "")
                    try:
                        from urllib.parse import urlparse as _up
                        domain = _up(url).netloc or url.split("/")[0]
                    except Exception:
                        domain = url[:50]
                import uuid as _uuid
                req_id = str(_uuid.uuid4())[:12]
                approved = await session.get_network_approval(req_id, url, domain, tool_name=tc.name)
                if not approved:
                    _denied_call_ids.add(tc.id)

            # Block denied web tool calls
            for tc in [t for t in tool_calls if t.id in _denied_call_ids]:
                await emit(ToolCallStartedEvent(
                    type="tool_call_started",
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    tool_input=tc.input,
                ))
                result_text = f"Network access to '{tc.input.get('url', tc.input.get('query', ''))}' was denied by user."
                await emit(ToolCallCompletedEvent(
                    type="tool_call_completed",
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    output=result_text,
                    duration_ms=0,
                ))
                tool_results.append({
                    "type": "function_call_output",
                    "call_id": tc.id,
                    "output": result_text,
                })
            tool_calls = [t for t in tool_calls if t.id not in _denied_call_ids]

            # Separate tool calls into parallel-safe and sequential groups
            read_only_calls = [tc for tc in tool_calls if tc.name in READ_ONLY_TOOLS]
            write_calls = [tc for tc in tool_calls if tc.name not in READ_ONLY_TOOLS]
            
            # Execute read-only tools in parallel
            if read_only_calls:
                async def execute_read_only_tool(tc):
                    """Execute a single read-only tool and return its result."""
                    if cancel_event.is_set():
                        return None
                    
                    call_id = tc.id
                    tool_name = tc.name
                    
                    await emit(ToolCallStartedEvent(
                        type="tool_call_started",
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        tool_input=tc.input,
                    ))
                    
                    from bob.core.session import ToolContext
                    ctx = ToolContext(session)
                    ctx.on_output_delta = on_output_delta
                    ctx.on_plan_update = on_plan_update
                    ctx.thread_manager = session.ensure_thread_manager()
                    ctx.on_request_user_input = session.request_user_input
                    
                    import time
                    t0 = time.monotonic()
                    tool_error: str | None = None
                    try:
                        result_text = await session.tool_registry.dispatch(
                            tool_name, tc.input, ctx
                        )
                    except Exception as exc:
                        result_text = f"Error: {exc}"
                        tool_error = result_text
                    duration_ms = int((time.monotonic() - t0) * 1000)
                    
                    await emit(ToolCallCompletedEvent(
                        type="tool_call_completed",
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        output=result_text,
                        duration_ms=duration_ms,
                        error=tool_error,
                    ))
                    
                    return {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": result_text,
                    }
                
                # Execute all read-only tools in parallel
                parallel_results = await asyncio.gather(
                    *[execute_read_only_tool(tc) for tc in read_only_calls],
                    return_exceptions=False
                )
                tool_results.extend([r for r in parallel_results if r is not None])
            
            # Execute write tools sequentially (includes shell, write_file, edit_file, etc.)
            for tc in write_calls:
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
                            error=result_text if result_text.startswith("Error:") else None,
                        ))
                        tool_results.append({
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": result_text,
                        })
                        continue

                    escalation_reason = detect_escalation(command)
                    approval_needed = escalation_reason is not None or needs_approval(
                        command,
                        session.config.ask_for_approval,
                        session_approved_commands,
                        trusted_patterns=session.config.trusted_commands,
                    )
                    approval_reason = escalation_reason or "Command requires approval per policy"

                    if approval_needed:
                        await emit(ExecApprovalRequestedEvent(
                            type="exec_approval_requested",
                            tool_call_id=call_id,
                            command=command,
                            cwd=str(exec_cwd),
                            reason=approval_reason,
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
                    try:
                        exec_result = await execute_command(
                            command=command,
                            cwd=exec_cwd,
                            sandbox=session._sandbox_runner,
                            cancel_event=cancel_event,
                            on_output_delta=on_delta,
                            timeout_ms=timeout_ms,
                        )
                    except Exception as _exec_exc:
                        # Sandbox block, permission error, or other failure — still
                        # need a tool result so the context stays valid.
                        result_text = f"Error: {_exec_exc}"
                        await emit(ExecCompletedEvent(
                            type="exec_completed",
                            tool_call_id=call_id,
                            exit_code=1,
                            status=ExecCommandStatus.FAILED,
                            duration_ms=0,
                        ))
                        await emit(ToolCallCompletedEvent(
                            type="tool_call_completed",
                            tool_call_id=call_id,
                            tool_name=tool_name,
                            output=result_text,
                            duration_ms=0,
                            error=result_text,
                        ))
                        tool_results.append({
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": result_text,
                        })
                        continue

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
                    ctx.thread_manager = session.ensure_thread_manager()
                    ctx.on_request_user_input = session.request_user_input

                    import time
                    t0 = time.monotonic()
                    tool_error: str | None = None
                    try:
                        result_text = await session.tool_registry.dispatch(
                            tool_name, tc.input, ctx
                        )
                    except Exception as exc:
                        result_text = f"Error: {exc}"
                        tool_error = result_text
                    duration_ms = int((time.monotonic() - t0) * 1000)

                    await emit(ToolCallCompletedEvent(
                        type="tool_call_completed",
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        output=result_text,
                        duration_ms=duration_ms,
                        error=tool_error,
                    ))

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
            cached_input_tokens=total_cached_input_tokens,
        ))

        if session._recorder:
            await session._recorder.write({
                "type": "turn_ended",
                "turn_id": turn_id,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "cached_input_tokens": total_cached_input_tokens,
            })

        # Analytics: record tokens, cost, latency, and changed files for this turn
        if hasattr(session, "analytics") and session.analytics is not None:
            changed = _diff_snapshot(_file_snapshot_before, _snapshot_dir(session.cwd))
            if changed:
                session.analytics.set_changed_files(changed)
            await session.analytics.finish_turn(total_input_tokens, total_output_tokens)

    except asyncio.CancelledError:
        await emit(TurnInterruptedEvent(
            type="turn_interrupted", turn_id=turn_id, graceful=False
        ))
        raise
