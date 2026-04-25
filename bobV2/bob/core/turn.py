from __future__ import annotations
import asyncio
import uuid
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
    TokenBudgetEvent,
    ErrorEvent,
    WarningEvent,
)
from bob.llm.client import (
    TextDeltaEvent as ClientTextDelta,
    ToolCallEvent as ClientToolCall,
    CompletedEvent as ClientCompleted,
    StreamErrorEvent as ClientStreamError,
    ReasoningDeltaEvent as ClientReasoningDelta,
)
from bob.protocol.config_types import AskForApproval

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


def _format_missing_provider_auth_message(provider: str, missing: list[str], env_vars: tuple[str, ...]) -> str:
    parts = [f"Missing auth for provider '{provider}'."]
    if "api_key" in missing and env_vars:
        joined = ", ".join(env_vars)
        parts.append(f"Set one of: {joined}.")
    elif missing:
        parts.append("Missing settings: " + ", ".join(missing) + ".")
    if provider == "kimi":
        parts.append("Kimi uses an OpenAI-compatible endpoint, but it still requires a Kimi credential.")
    return " ".join(parts)


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
            # Don't hard-block â€” just force approval
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
        # it via ExecOutputEvent but need the call_id â€” shell tool directly
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
    context_recovery_attempts = 0
    max_compact_retries = max(1, int(getattr(session.config, "compact_max_retries", 3) or 3))

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
            allowed_tools = getattr(session, "_allowed_tools", None)
            if allowed_tools:
                filtered_specs: list[dict] = []
                for s in tool_specs:
                    name = s.get("name")
                    if name is None:
                        name = s.get("function", {}).get("name")
                    if name in allowed_tools:
                        filtered_specs.append(s)
                tool_specs = filtered_specs
            # In plan mode: only expose non-mutating tools.
            if getattr(session, "_plan_mode", False):
                filtered_specs: list[dict] = []
                for s in tool_specs:
                    name = s.get("name")
                    if name is None:
                        name = s.get("function", {}).get("name")
                    if name and not session.tool_registry.get_tool_capabilities(name).is_mutating:
                        filtered_specs.append(s)
                tool_specs = filtered_specs

            text_parts: list[str] = []
            tool_calls: list[ClientToolCall] = []
            reasoning_parts: list[str] = []
            iter_input_tokens = 0
            iter_output_tokens = 0
            stream_error_message: str | None = None

            # ----------------------------------------------------------
            # Stream from model
            # ----------------------------------------------------------
            from bob.llm.compatibility import (
                build_model_request_params,
                get_provider_profile,
            )

            compatibility, _provider_auth = session.get_model_runtime(session.config.model)
            if _provider_auth.missing:
                profile = get_provider_profile(compatibility.provider)
                await emit(ErrorEvent(
                    type="error",
                    message=_format_missing_provider_auth_message(
                        compatibility.provider,
                        list(_provider_auth.missing),
                        profile.api_key_env_vars,
                    ),
                ))
                await emit(TurnEndedEvent(
                    type="turn_ended",
                    turn_id=turn_id,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                ))
                return
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
                        reasoning_parts.append(ev.delta)
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
                        stream_error_message = ev.message
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

            if stream_error_message:
                from bob.core.context_errors import classify_context_error

                classification = classify_context_error(stream_error_message)
                if (
                    classification.kind == "context_window_exceeded"
                    and getattr(session.config, "enable_reactive_compaction", True)
                ):
                    if context_recovery_attempts < max_compact_retries:
                        context_recovery_attempts += 1
                        if context_recovery_attempts == 1 and session.context_manager.size > 1:
                            session.context_manager.remove_first_item()
                            await emit(WarningEvent(
                                type="warning",
                                message="Context window exceeded. Retrying after trimming oldest history item.",
                            ))
                            continue

                        compacted = await session.compact_history(
                            reason="context_window_exceeded",
                            sub_id=sub_id,
                        )
                        if compacted:
                            await emit(WarningEvent(
                                type="warning",
                                message="Recovered from context overflow by compacting history and continuing.",
                            ))
                            continue
                    await emit(ErrorEvent(
                        type="error",
                        message=(
                            "Context window exceeded and recovery attempts were exhausted. "
                            "Please start a new thread or compact manually."
                        ),
                    ))
                    break

                if classification.kind == "max_output_exceeded":
                    session.context_manager.record_items([{
                        "role": "user",
                        "content": [{
                            "type": "input_text",
                            "text": "Continue from where you stopped. Do not repeat prior text.",
                        }],
                    }])
                    await emit(WarningEvent(
                        type="warning",
                        message="Model hit output limits. Auto-continuing response.",
                    ))
                    continue

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
            #   - text â†’ {"role":"assistant","content":[{"type":"output_text",...}]}
            #   - each tool call â†’ top-level {"type":"function_call",...}
            # ----------------------------------------------------------
            import json as _json

            history_items: list[dict] = []
            reasoning_text = "".join(reasoning_parts)
            assistant_item_needed = bool(full_text or reasoning_text or tool_calls)
            if assistant_item_needed:
                assistant_item = {
                    "role": "assistant",
                    "content": (
                        [{"type": "output_text", "text": full_text}]
                        if full_text
                        else []
                    ),
                }
                if reasoning_text:
                    assistant_item["reasoning_content"] = reasoning_text
                history_items.append(assistant_item)
            for tc in tool_calls:
                tool_call_item = {
                    "type": "function_call",
                    "call_id": tc.id,
                    "name": tc.name,
                    "arguments": _json.dumps(tc.input),
                }
                if tc.provider_specific_fields:
                    tool_call_item["provider_specific_fields"] = tc.provider_specific_fields
                history_items.append(tool_call_item)

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
            from bob.core.tool_orchestrator import ToolOrchestrator, TurnAbortRequested

            orchestrator = ToolOrchestrator(
                session=session,
                emit=emit,
                cancel_event=cancel_event,
                turn_id=turn_id,
                on_output_delta=on_output_delta,
                on_plan_update=on_plan_update,
                session_approved_commands=session_approved_commands,
                needs_approval_fn=needs_approval,
                detect_escalation_fn=detect_escalation,
            )
            try:
                tool_results = await orchestrator.execute_calls(tool_calls)
            except TurnAbortRequested:
                return

            # Record tool results into context and continue loop
            if tool_results:
                session.context_manager.record_items(tool_results)
                if session._recorder:
                    await session._recorder.write({
                        "type": "tool_results",
                        "turn_id": turn_id,
                        "results": tool_results,
                    })

                if getattr(session.config, "enable_mid_turn_compaction", True):
                    from bob.core.context_budget import compute_context_budget

                    budget = compute_context_budget(session)
                    token_count = session.context_manager.approx_token_count()
                    if token_count >= budget.effective_context_window:
                        await session.compact_history(
                            reason="mid_turn_continuation",
                            sub_id=sub_id,
                        )

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
            await session.analytics.finish_turn(
                total_input_tokens,
                total_output_tokens,
                total_cached_input_tokens,
            )

    except asyncio.CancelledError:
        await emit(TurnInterruptedEvent(
            type="turn_interrupted", turn_id=turn_id, graceful=False
        ))
        raise
