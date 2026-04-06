from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ReconstructionResult:
    """Output of :func:`reconstruct_history`."""

    history: list[dict]
    previous_model: Optional[str] = None
    previous_cwd: Optional[str] = None


def _drop_user_turns(history: list[dict], n: int) -> list[dict]:
    """
    Remove the last *n* user-turn boundaries (and everything after each one)
    from *history*.  Returns the truncated copy.
    """
    result = list(history)
    dropped = 0
    while dropped < n and result:
        found = False
        for j in range(len(result) - 1, -1, -1):
            item = result[j]
            if item.get("role") == "user" and "tool_call_id" not in item:
                result = result[:j]
                dropped += 1
                found = True
                break
        if not found:
            break
    return result


def reconstruct_history(rollout_items: list[dict]) -> ReconstructionResult:
    """
    Reconstruct the live conversation history from a JSONL rollout record list.

    Algorithm
    ---------
    Phase 1 – backward scan
        Walk from newest to oldest looking for the latest ``compacted`` record.
        When found, use its ``replacement_history`` as the base and set the
        surviving suffix to everything that follows it.  Also note any
        ``thread_rolled_back`` or ``turn_context`` records encountered during
        the scan so the caller has metadata about the session.

    Phase 2 – forward replay
        Replay ``rollout_suffix`` forward, applying:
          * ``response_item``      → append the inner item to history
          * ``compacted``          → replace history with replacement_history
          * ``thread_rolled_back`` → drop the specified number of user turns

    This faithfully reproduces the state the conversation was in when the
    rollout file was last written.
    """
    previous_model: Optional[str] = None
    previous_cwd: Optional[str] = None
    base_history: Optional[list[dict]] = None
    rollout_suffix: list[dict] = rollout_items

    # ------------------------------------------------------------------ #
    # Phase 1: backward scan to find latest compaction + collect metadata #
    # ------------------------------------------------------------------ #
    for i in range(len(rollout_items) - 1, -1, -1):
        item = rollout_items[i]
        item_type = item.get("type")

        if item_type == "compacted":
            replacement = item.get("replacement_history")
            if isinstance(replacement, list):
                base_history = replacement
                rollout_suffix = rollout_items[i + 1 :]
                break  # found newest compaction; stop backward scan

        elif item_type == "turn_context":
            # Collect metadata from the most recent turn_context record.
            if previous_model is None:
                previous_model = item.get("model")
            if previous_cwd is None:
                previous_cwd = item.get("cwd")

        # Note: thread_rolled_back records in the backward scan phase are
        # only counted when there is no base compaction at all (handled in
        # phase 2 on the full list in that case).

    # ------------------------------------------------------------------ #
    # Phase 2: forward replay of the surviving suffix                     #
    # ------------------------------------------------------------------ #
    history: list[dict] = list(base_history) if base_history is not None else []

    for item in rollout_suffix:
        item_type = item.get("type")

        if item_type == "response_item":
            resp = item.get("item")
            if isinstance(resp, dict):
                history.append(resp)

        elif item_type == "compacted":
            replacement = item.get("replacement_history")
            if isinstance(replacement, list):
                history = list(replacement)

        elif item_type == "thread_rolled_back":
            n = item.get("num_turns", 1)
            if isinstance(n, int) and n > 0:
                history = _drop_user_turns(history, n)

        # Other record types (session_meta, turn_context, exec_result, …)
        # carry observational metadata and do not affect the reconstructed
        # conversation history.

    return ReconstructionResult(
        history=history,
        previous_model=previous_model,
        previous_cwd=previous_cwd,
    )
