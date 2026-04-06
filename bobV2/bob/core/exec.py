from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from bob.sandbox.base import SandboxRunner

DEFAULT_TIMEOUT_MS = 30_000  # 30 s default; many Windows ops are slower
MAX_OUTPUT_BYTES = 500_000   # 500 KB hard cap on captured output
MAX_DELTA_EVENTS = 10_000   # maximum streaming delta callbacks
IO_DRAIN_TIMEOUT = 2.0      # seconds to wait for IO after kill


def _build_ps_command(args: list[str]) -> str:
    """Convert a command+args list into a single PowerShell -Command string."""
    parts = []
    for a in args:
        # Quote args that contain spaces or special PS chars
        if any(c in a for c in (' ', '"', "'", '(', ')', '{', '}', '$', '`', ';', '|', '&', '>', '<', ',')):
            escaped = a.replace("'", "''")
            parts.append(f"'{escaped}'")
        else:
            parts.append(a)
    return " ".join(parts)


@dataclass
class ExecResult:
    """Result of a sandboxed command execution."""

    stdout: str
    stderr: str
    aggregated_output: str
    exit_code: int
    duration_ms: int
    timed_out: bool = False


async def execute_command(
    command: list[str],
    cwd: Path,
    sandbox: SandboxRunner,
    env: Optional[dict[str, str]] = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    cancel_event: Optional[asyncio.Event] = None,
    on_output_delta: Optional[Callable[[str, str], Awaitable[None]]] = None,
) -> ExecResult:
    """
    Execute *command* inside *sandbox* with full streaming, output cap, timeout,
    and process-group kill.

    Parameters
    ----------
    command:
        The command and its arguments (pre-sandbox-wrapping).
    cwd:
        Working directory for the process.
    sandbox:
        SandboxRunner whose wrap_command() is applied before execution.
    env:
        Extra environment variables merged on top of os.environ.
    timeout_ms:
        Hard wall-clock timeout in milliseconds.  The process group is killed
        on expiry and exit_code is set to 124 (conventional timeout code).
    cancel_event:
        An asyncio.Event that, when set, triggers early termination identical
        to a timeout.
    on_output_delta:
        Async callback invoked for each captured chunk.
        Signature: ``async def cb(data: str, stream: str) -> None``
        where *stream* is ``"stdout"`` or ``"stderr"``.
    """
    wrapped = sandbox.wrap_command(command)

    exec_env = os.environ.copy()
    if env:
        exec_env.update(env)

    # On Windows run through PowerShell unless the command already IS powershell.
    if sys.platform == "win32":
        cmd0 = wrapped[0].lower().replace(".exe", "").replace(".cmd", "")
        already_ps = cmd0 in ("powershell", "pwsh")
        if already_ps:
            launch = wrapped  # model explicitly called powershell — use as-is
        else:
            ps_cmd = _build_ps_command(wrapped)
            launch = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd]
    else:
        launch = wrapped

    start_time = time.monotonic()

    # start_new_session is unsupported on Windows; use creationflags instead.
    kwargs: dict = dict(
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=exec_env,
    )
    if sys.platform == "win32":
        import subprocess as _sp
        kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    proc = await asyncio.create_subprocess_exec(*launch, **kwargs)

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    total_bytes = 0
    delta_count = 0

    async def read_stream(
        stream: asyncio.StreamReader,
        name: str,
        chunks: list[bytes],
    ) -> None:
        nonlocal total_bytes, delta_count
        while True:
            try:
                chunk = await stream.read(8192)
                if not chunk:
                    break
                if total_bytes < MAX_OUTPUT_BYTES:
                    chunks.append(chunk)
                    total_bytes += len(chunk)
                if delta_count < MAX_DELTA_EVENTS and on_output_delta is not None:
                    text = chunk.decode("utf-8", errors="replace")
                    delta_count += 1
                    await on_output_delta(text, name)
            except Exception:
                break

    stdout_task = asyncio.create_task(
        read_stream(proc.stdout, "stdout", stdout_chunks)
    )
    stderr_task = asyncio.create_task(
        read_stream(proc.stderr, "stderr", stderr_chunks)
    )

    timed_out = False
    timeout_s = timeout_ms / 1000.0

    # --- Wait for process completion, timeout, or external cancellation ----
    try:
        if cancel_event is not None:
            proc_wait_task = asyncio.create_task(proc.wait())
            cancel_task = asyncio.create_task(cancel_event.wait())
            done, pending = await asyncio.wait(
                {proc_wait_task, cancel_task},
                timeout=timeout_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            # Cancel whichever helper task is still running
            for t in pending:
                t.cancel()
            if cancel_event.is_set():
                timed_out = True
            elif not done:
                # Neither completed within timeout
                timed_out = True
        else:
            await asyncio.wait_for(proc.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        timed_out = True

    # --- Kill process group if timed out or cancelled ----------------------
    if timed_out or (cancel_event is not None and cancel_event.is_set()):
        try:
            if sys.platform == "win32":
                proc.kill()
            else:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass

        # Drain remaining IO with a hard deadline to avoid hanging forever
        try:
            await asyncio.wait_for(
                asyncio.gather(stdout_task, stderr_task, return_exceptions=True),
                timeout=IO_DRAIN_TIMEOUT,
            )
        except asyncio.TimeoutError:
            stdout_task.cancel()
            stderr_task.cancel()
    else:
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

    # Ensure the process has fully exited so returncode is populated
    try:
        await asyncio.wait_for(proc.wait(), timeout=1.0)
    except (asyncio.TimeoutError, Exception):
        pass

    exit_code: int
    if timed_out:
        exit_code = 124  # conventional timeout exit code (same as `timeout` utility)
    elif proc.returncode is not None:
        exit_code = proc.returncode
    else:
        exit_code = -1

    stdout_text = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")

    if stderr_text.strip():
        aggregated = (stdout_text + "\n" + stderr_text).strip()
    else:
        aggregated = stdout_text

    duration_ms = int((time.monotonic() - start_time) * 1000)

    return ExecResult(
        stdout=stdout_text,
        stderr=stderr_text,
        aggregated_output=aggregated,
        exit_code=exit_code,
        duration_ms=duration_ms,
        timed_out=timed_out,
    )
