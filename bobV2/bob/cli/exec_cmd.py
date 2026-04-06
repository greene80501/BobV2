from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional


async def run_exec(
    prompt: Optional[str],
    model: Optional[str],
    sandbox: Optional[str],
    approval: Optional[str],
    resume_id: Optional[str],
    resume_last: bool,
    json_output: bool,
    ephemeral: bool,
    full_auto: bool,
    yolo: bool,
    cwd: Optional[Path],
    output_file: Optional[Path],
) -> None:
    from bob.config.loader import load_config
    from bob.protocol.config_types import AskForApproval, SandboxMode

    work_dir = cwd or Path.cwd()

    # Read prompt from stdin if not provided or explicitly set to "-"
    if prompt is None or prompt == "-":
        if not sys.stdin.isatty():
            prompt = sys.stdin.read()
        else:
            print("Error: no prompt provided and stdin is a terminal.", file=sys.stderr)
            sys.exit(1)

    cli_overrides: dict = {}
    if model:
        cli_overrides["model"] = model
    if sandbox:
        cli_overrides["sandbox_mode"] = sandbox
    if approval:
        cli_overrides["approval_policy"] = approval
    if full_auto:
        cli_overrides["ask_for_approval"] = AskForApproval.ON_REQUEST.value
        cli_overrides["sandbox_mode"] = SandboxMode.WORKSPACE_WRITE.value
    if yolo:
        cli_overrides["ask_for_approval"] = AskForApproval.NEVER.value
        cli_overrides["sandbox_mode"] = SandboxMode.DANGER_FULL_ACCESS.value

    config = load_config(cwd=work_dir, cli_overrides=cli_overrides)

    from bob.core.session import BobSession
    from bob.protocol.ops import UserTurnOp, InterruptOp, ExecApprovalOp
    from bob.protocol.items import TextUserInput
    from bob.protocol.events import (
        TurnEndedEvent,
        TurnInterruptedEvent,
        TextDeltaEvent,
        TextFinalEvent,
        ExecStartedEvent,
        ExecOutputEvent,
        ExecCompletedEvent,
        ExecApprovalRequestedEvent,
        ErrorEvent,
        TokenBudgetEvent,
        CostEstimateEvent,
    )
    from bob.protocol.config_types import ReviewDecision

    session = BobSession(config=config, cwd=work_dir, ephemeral=ephemeral)
    await session.start()

    if resume_last or resume_id:
        sessions = await session.list_sessions()
        if resume_last and sessions:
            await session.resume(sessions[0].path)
        elif resume_id:
            await session.resume_by_id(resume_id)

    await session.submit(
        UserTurnOp(
            items=[TextUserInput(type="text", text=prompt)],
        )
    )

    last_message = ""
    in_text_stream = False

    async for event in session.events():
        msg = event.msg

        if json_output:
            try:
                print(
                    json.dumps({"id": event.id, "msg": msg.model_dump()}),
                    flush=True,
                )
            except Exception as e:
                print(
                    json.dumps({"id": event.id, "error": str(e)}),
                    flush=True,
                )

        if isinstance(msg, TextDeltaEvent):
            if not in_text_stream and not json_output:
                in_text_stream = True
            if not json_output:
                print(msg.delta, end="", flush=True)
            last_message += msg.delta

        elif isinstance(msg, TextFinalEvent):
            # If no deltas were received, output the full text now
            if not last_message and not json_output:
                print(msg.text, end="", flush=True)
                last_message = msg.text
            in_text_stream = False

        elif isinstance(msg, ExecStartedEvent):
            if not json_output:
                cmd_str = " ".join(msg.command)
                print(f"\n$ {cmd_str}", flush=True)

        elif isinstance(msg, ExecOutputEvent):
            if not json_output:
                print(msg.data, end="", flush=True)

        elif isinstance(msg, ExecCompletedEvent):
            if not json_output and msg.exit_code != 0:
                print(f"\n[exit {msg.exit_code}]", flush=True)

        elif isinstance(msg, ExecApprovalRequestedEvent):
            ask_for_approval = getattr(config, "ask_for_approval", None)
            never_approve = (
                ask_for_approval is not None
                and ask_for_approval.value == "never"
            )
            if never_approve or yolo:
                await session.submit(
                    ExecApprovalOp(
                        tool_call_id=msg.tool_call_id,
                        decision=ReviewDecision.APPROVED,
                    )
                )
            else:
                # Interactive approval via stdin
                cmd_str = " ".join(msg.command)
                print(f"\n⚠ Approval required: $ {cmd_str}", flush=True)
                print("[y] Approve  [n] Deny: ", end="", flush=True)
                try:
                    answer = input().strip().lower()
                except EOFError:
                    answer = "n"
                decision = (
                    ReviewDecision.APPROVED if answer == "y" else ReviewDecision.DENIED
                )
                await session.submit(
                    ExecApprovalOp(
                        tool_call_id=msg.tool_call_id,
                        decision=decision,
                    )
                )

        elif isinstance(msg, ErrorEvent):
            print(f"\nError: {msg.message}", file=sys.stderr)
            if msg.fatal:
                break

        elif isinstance(msg, (TurnEndedEvent, TurnInterruptedEvent)):
            if not json_output and in_text_stream:
                print()  # final newline after streaming text
            break

    if output_file and last_message:
        output_file.write_text(last_message, encoding="utf-8")

    await session.shutdown()
