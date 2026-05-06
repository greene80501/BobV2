from __future__ import annotations

from pathlib import Path

from bob.plugins.manager import PluginInfo


def list_demo_plugins() -> list[PluginInfo]:
    base = Path.home() / ".bob" / "plugins"
    return [
        PluginInfo(
            name="github",
            version="2.4.1",
            description="GitHub repository, issue, pull request, and CI workflow integration.",
            path=base / "github",
        ),
        PluginInfo(
            name="gmail",
            version="1.8.0",
            description="Inbox search, thread summaries, draft replies, and mailbox triage.",
            path=base / "gmail",
        ),
        PluginInfo(
            name="linear",
            version="1.3.2",
            description="Issue lookup, project status, cycle planning, and ticket updates.",
            path=base / "linear",
        ),
        PluginInfo(
            name="postgres",
            version="0.9.6",
            description="Read-only database inspection, schema browsing, and query helpers.",
            path=base / "postgres",
        ),
    ]
