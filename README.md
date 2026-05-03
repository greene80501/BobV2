# Bob V2 Repository

This repository is centered on the `bobV2/` Python project.

Current layout:

- `bobV2/`: the Bob V2 CLI, TUI, tool system, app server, and built-in Chrome bridge
- `chrome_extension/`: the Chrome side panel extension that connects to Bob over `ws://localhost:9876`
- `bobV2/chacter/`: character art and local helper assets
- `BOB_V2_PITCH.md`: product and positioning notes

Important runtime detail:

- The Chrome extension does not use the old top-level `api_bridge.py`.
- Browser control now comes from `bobV2/bob/bridge/chrome_bridge.py`, which Bob starts automatically in each session.

Typical local startup:

```powershell
cd bobV2
py -3.11 -m pip install -e .
bob
```
