from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class InterAgentMessage:
    author: str        # "parent" or an agent_id
    content: str
    trigger_turn: bool = True  # wake the recipient's session loop


class Mailbox:
    """Per-agent inbox backed by an asyncio.Queue."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[InterAgentMessage] = asyncio.Queue()
        self._trigger = asyncio.Event()

    def send(self, msg: InterAgentMessage) -> None:
        self._queue.put_nowait(msg)
        if msg.trigger_turn:
            self._trigger.set()

    def drain(self) -> list[InterAgentMessage]:
        msgs: list[InterAgentMessage] = []
        while not self._queue.empty():
            try:
                msgs.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        self._trigger.clear()
        return msgs

    def has_trigger(self) -> bool:
        return self._trigger.is_set()

    def is_empty(self) -> bool:
        return self._queue.empty()
