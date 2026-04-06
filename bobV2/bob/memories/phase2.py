from __future__ import annotations
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bob.client.openai_client import BobClient
    from bob.memories.storage import MemoryStorage

# Character cap on the combined summaries fed to the consolidation prompt
_MAX_COMBINED_CHARS = 12_000


async def consolidate_memories(
    storage: "MemoryStorage",
    client: "BobClient",
) -> Optional[str]:
    """Phase 2: consolidate all per-session summaries into a single memory document.

    Reads every ``.md`` file from ``storage.summaries_dir``, sends them to the
    model for de-duplication and organisation, then writes the result back via
    ``storage.write_consolidated()``.

    Returns the consolidated text, or ``None`` if there were no summaries or
    consolidation failed.
    """
    from bob.client.openai_client import TextDeltaEvent

    summaries = storage.read_all_summaries()
    if not summaries:
        return None

    combined = "\n\n---\n\n".join(summaries)
    if len(combined) > _MAX_COMBINED_CHARS:
        combined = combined[-_MAX_COMBINED_CHARS:]

    consolidation_prompt = (
        "Consolidate the following memory summaries from multiple development sessions "
        "into a single, well-organised memory document.\n\n"
        "Rules:\n"
        "- Remove duplicates; keep the most specific or recent version.\n"
        "- Group related facts under clear headings (e.g. User Preferences, "
        "Project Conventions, Technologies, Decisions).\n"
        "- Keep entries concise — short bullet points are preferred.\n"
        "- Drop information that is no longer actionable or is too vague to be useful.\n\n"
        f"Summaries:\n{combined}\n\n"
        "Write the consolidated memory document."
    )

    parts: list[str] = []
    try:
        async for ev in client.stream_turn(
            input=[{
                "role": "user",
                "content": [{"type": "input_text", "text": consolidation_prompt}],
            }],
            instructions=(
                "Consolidate these memory summaries into a single concise document. "
                "Use markdown headings and bullet points."
            ),
            tools=[],
        ):
            if isinstance(ev, TextDeltaEvent):
                parts.append(ev.delta)
    except Exception:
        return None

    result = "".join(parts).strip()
    if not result:
        return None

    storage.write_consolidated(result)
    return result
