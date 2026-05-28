# Bob V2 Repository

Bob V2 is an experimental terminal-first AI coding assistant prototype. It can chat about a codebase, read and edit files, run approved shell commands, review diffs, create commits, launch subagents, and connect to a Chrome extension for browser control.

Bob runs from the `bobV2/` Python project. When you start Bob, it opens an interactive terminal UI, creates a session, sends your request to the selected model provider, and lets the model call approved tools such as file search, file editing, shell commands, subagents, and browser actions. Runtime state, sessions, logs, config, and local secrets live outside Git under Bob's local runtime directory.

## Where To Go Next

- For setup, API keys, running Bob, slash commands, subagents, provider config, development notes, and the project disclaimer, read [bobV2/README.md](bobV2/README.md).
- For installing and using the browser side panel, read [chrome_extension/README.md](chrome_extension/README.md).
- For MacBook-specific setup, read [bobV2/MACBOOK_SETUP.md](bobV2/MACBOOK_SETUP.md).

## Repository Layout

- `bobV2/`: the Python CLI, TUI, tool system, app server, sessions, plugins, MCP support, and built-in Chrome bridge.
- `chrome_extension/`: the Chrome side panel extension that connects to Bob over `ws://localhost:9876`.
- `bobV2/chacter/`: character art and local helper assets.
- `BOB_V2_PITCH.md`: product and positioning notes.

## Quick Start

```powershell
cd bobV2
py -3.11 -m pip install -e .
py -3.11 -m bob
```

The Chrome extension does not use a separate top-level API bridge. Browser control comes from `bobV2/bob/bridge/chrome_bridge.py`, which Bob starts automatically during a session.
