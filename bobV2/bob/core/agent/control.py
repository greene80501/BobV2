from __future__ import annotations
import asyncio


class AgentControl:
    """Controls for interrupting and monitoring agent turns.

    Used by the TUI and CLI to cancel an in-progress turn without needing
    direct access to the underlying asyncio.Task.

    Example::

        control = AgentControl()
        # From another coroutine or thread:
        control.cancel()
        # The running turn checks control.is_cancelled periodically
    """

    def __init__(self) -> None:
        self._cancel = asyncio.Event()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Signal the current turn to stop as soon as possible."""
        self._cancel.set()

    def reset(self) -> None:
        """Clear the cancellation signal (call before starting a new turn)."""
        self._cancel.clear()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    @property
    def is_cancelled(self) -> bool:
        """True if a cancellation has been requested."""
        return self._cancel.is_set()

    @property
    def cancel_event(self) -> asyncio.Event:
        """The underlying asyncio.Event, suitable for passing to coroutines
        that accept a *cancel_event* parameter."""
        return self._cancel

    # ------------------------------------------------------------------
    # Context manager support (resets on entry, available to pass around)
    # ------------------------------------------------------------------

    def __enter__(self) -> "AgentControl":
        self.reset()
        return self

    def __exit__(self, *_) -> None:
        # Ensure the event is cleared after the block regardless of outcome
        self.reset()

    def __repr__(self) -> str:
        return f"AgentControl(cancelled={self.is_cancelled})"
