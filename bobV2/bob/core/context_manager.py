from __future__ import annotations

import json
from typing import Optional


class ContextManager:
    """
    Manages conversation history as a list of ResponseItem dicts.

    Items follow the OpenAI Responses API shape:
      {"role": "user"|"assistant", "content": [...], ...}
    Tool results carry a "tool_call_id" key instead of a top-level role.
    """

    def __init__(self) -> None:
        self._items: list[dict] = []

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def record_items(self, items: list[dict]) -> None:
        """Append a batch of items to the history."""
        self._items.extend(items)

    def raw_items(self) -> list[dict]:
        """Return a shallow copy of the full history."""
        return list(self._items)

    def replace(self, items: list[dict]) -> None:
        """Replace the entire history with a new list."""
        self._items = list(items)

    def remove_first_item(self) -> None:
        """Drop the oldest item from history (used for context trimming)."""
        if self._items:
            self._items.pop(0)

    def drop_last_n_user_turns(self, n: int) -> None:
        """
        Drop the last *n* user-turn boundaries from history.

        A user-turn boundary is defined as a message with role="user" that is
        not a tool result (i.e. it does not carry a "tool_call_id" key).
        Everything from that boundary onward is removed in each pass.
        """
        dropped = 0
        while dropped < n and self._items:
            # Scan backward for the last user-turn boundary
            found = False
            for i in range(len(self._items) - 1, -1, -1):
                if self.is_user_turn_boundary(self._items[i]):
                    self._items = self._items[:i]
                    dropped += 1
                    found = True
                    break
            if not found:
                break

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def approx_token_count(self) -> int:
        """Rough token estimate: total JSON character count divided by 4."""
        text = json.dumps(self._items)
        return len(text) // 4

    def is_user_turn_boundary(self, item: dict) -> bool:
        """Return True if *item* represents the start of a user turn."""
        return item.get("role") == "user" and "tool_call_id" not in item

    @property
    def size(self) -> int:
        """Number of items currently in history."""
        return len(self._items)

    def __len__(self) -> int:
        return self.size

    def __repr__(self) -> str:
        return f"ContextManager(size={self.size}, approx_tokens={self.approx_token_count()})"
