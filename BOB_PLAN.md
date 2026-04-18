# BOB — Complete Technical Reference

> Full architecture, tools, features, slash commands, TUI, config, and internals.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              bob process                                │
│                                                                         │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────────────────┐  │
│  │  CLI /   │    │  BobSession  │    │       LLM Client             │  │
│  │  TUI     │───▶│  (session.py)│───▶│  LiteLLMClient (LiteLLM)    │  │
│  │          │    │              │    │  BobClient (OpenAI Responses) │  │
│  └──────────┘    └──────┬───────┘    └──────────────────────────────┘  │
│                         │                                               │
│          ┌──────────────┼──────────────┐                               │
│          ▼              ▼              ▼                               │
│  ┌──────────────┐ ┌──────────┐ ┌─────────────┐                        │
│  │ ToolRegistry │ │ Context  │ │  Sandbox    │                        │
│  │  (tools/)    │ │ Manager  │ │  Runner     │                        │
│  └──────┬───────┘ └──────────┘ └─────────────┘                        │
│         │                                                               │
│  ┌──────┴──────────────────────────────────────────┐                   │
│  │                  Tool Handlers                   │                   │
│  │  shell · read_file · write_file · edit_file      │                   │
│  │  web_fetch · web_search · spawn_agent · ...      │                   │
│  └─────────────────────────────────────────────────┘                   │
│                                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                 │
│  │  MCP Manager │  │ Plugin Mgr   │  │  Analytics   │                 │
│  │  (mcp/)      │  │ (plugins/)   │  │  (analytics/)│                 │
│  └──────────────┘  └──────────────┘  └──────────────┘                 │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  App Server (JSON-RPC 2.0 over stdio or WebSocket)               │  │
│  │  Routes: agents · config · exec · files · tasks · turns · ...    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Concern | Library | Notes |
|---------|---------|-------|
| Language | Python 3.11+ | Required minimum |
| TUI | `prompt_toolkit` | Input, key bindings, history, autocomplete |
| CLI | `typer` | `bob`, `bob exec`, `bob app-server`, `bob config`, `bob mcp`, `bob plugin` |
| LLM (primary) | `openai` SDK | OpenAI Responses API for GPT-5/o-series/codex models |
| LLM (multi-provider) | `litellm` | All other providers via chat completions |
| Data models | `pydantic` v2 | Config, protocol events, MCP types |
| Config | `tomllib` (stdlib) + `tomli_w` | Read/write `~/.bob/config.toml` |
| SQLite | `aiosqlite` | Session persistence, rollout storage, analytics |
| Async | `asyncio` | All I/O, event loops, subprocess management |
| MCP | `mcp` Python SDK | Model Context Protocol server connections |
| Fuzzy match | `rapidfuzz` | Slash command autocomplete |
| Screenshots | `mss` + `Pillow` | Computer use tool (optional) |
| GUI automation | `pyautogui` | Computer use tool (optional) |

---

## Entry Points

### Interactive TUI
```
bob                              # Launch TUI
bob -p "initial prompt"          # Launch TUI with message pre-queued
bob --resume SESSION_ID          # Resume session
bob --model MODEL                # Override model
bob --sandbox MODE               # Override sandbox
bob --approval POLICY            # Override approval policy
bob -C /path                     # Override working directory
```

### Headless (non-interactive)
```
bob exec PROMPT
bob exec --last PROMPT           # Resume most recent session
bob exec --resume SESSION_ID
bob exec --json PROMPT           # JSONL event output
bob exec --ephemeral PROMPT      # No session persistence
bob exec --full-auto PROMPT      # Auto-approve everything
bob exec --yolo PROMPT           # Bypass all approvals and sandbox
bob exec -o output.txt PROMPT    # Save last message to file
```

### App Server (IDE integration)
```
bob app-server --stdio           # stdin/stdout JSON-RPC 2.0
bob app-server --port 8765       # WebSocket JSON-RPC 2.0
```

### Config CLI
```
bob config set KEY VALUE
bob config get KEY
bob config unset KEY
bob config list
```

### MCP CLI
```
bob mcp add NAME COMMAND [ARGS]
bob mcp list
```

### Plugin CLI
```
bob plugin list
bob plugin install SOURCE
bob plugin uninstall NAME
bob plugin search QUERY
```

---

## Session Lifecycle

```
bob start
  └─ load_config()                    # ~/.bob/config.toml + env vars + CLI overrides
  └─ BobSession.__init__()
      ├─ _make_client(model)          # route to LiteLLMClient or BobClient
      ├─ register all tools           # ToolRegistry.register(...)
      ├─ start MCP servers            # McpManager.start()
      ├─ load skills                  # SkillManager.discover()
      ├─ load hooks                   # HookRunner setup
      └─ start analytics              # AnalyticsDB, AnalyticsTracker
  └─ run_interface()                  # prompt_toolkit TUI loop
      └─ on user input:
          └─ session.submit(UserTurnOp)
              └─ execute_turn()
                  ├─ build system prompt
                  ├─ get tool_specs from ToolRegistry
                  ├─ normalize tools: flat → chat-completions format
                  ├─ sanitize tool names to ^[a-zA-Z][a-zA-Z0-9_-]*$
                  ├─ stream_turn() → LLM
                  ├─ dispatch tool calls → ToolRegistry
                  ├─ auto-compact if near context limit
                  └─ persist to rollout DB
```

---

## LLM Client Routing

```
Model string                          Route
──────────────────────────────────────────────────────────────
gpt-5.1-codex-mini                    OpenAI Responses API (BobClient)
gpt-5.x, o1, o3, o4, codex-*         OpenAI Responses API (BobClient)
gpt-4o, gpt-4o-mini, gpt-4-*         LiteLLM chat (openai/)
anthropic/claude-*                    LiteLLM chat (anthropic/)
gemini/gemini-*                       LiteLLM chat (gemini/)
vertex_ai/gemini-*                    LiteLLM chat (vertex_ai/)
azure/<deployment>                    LiteLLM chat (azure/)
kimi/kimi-for-coding                  LiteLLM → https://api.kimi.com/coding/v1
openrouter/*                          LiteLLM chat (openrouter/)
groq/*, mistral/*, xai/*             LiteLLM chat
together_ai/*                         LiteLLM chat
ollama/*                              LiteLLM chat (local)
```

**Tool format pipeline** (in `llm/client.py _stream_once`):
1. `_normalize_tools_to_chat_format()` — flat Responses-API → nested Chat-Completions
2. `_sanitize_tools()` — coerce names to `^[a-zA-Z][a-zA-Z0-9_-]*$`
3. `_patch_message_tool_names()` — apply same remap to history
4. On ToolCallEvent yield — restore original names from reverse map

**Kimi for Coding special handling** (`llm/compatibility.py`):
- Provider profile auto-sets `base_url = https://api.kimi.com/coding/v1`
- Auto-injects headers: `User-Agent: claude-code/1.0`, `X-Client-Name: claude-code`
- Canonical model: `openai/kimi-for-coding` (routes via LiteLLM OpenAI path)
- API key: `KIMI_API_KEY` env var (from kimi.com/coding, NOT platform.moonshot.ai)

---

## Supported Providers

| Provider | Model prefix | Env var | Notes |
|----------|-------------|---------|-------|
| OpenAI | `gpt-*`, `o1/o3/o4`, `codex-*` | `OPENAI_API_KEY` | GPT-5/codex → Responses API |
| Anthropic | `anthropic/claude-*` | `ANTHROPIC_API_KEY` | Prompt caching supported |
| Gemini | `gemini/gemini-*` | `GEMINI_API_KEY` | Auto-prefixes bare `gemini-*` |
| Vertex AI | `vertex_ai/gemini-*` | `VERTEXAI_LOCATION` + GCP creds | |
| Azure OpenAI | `azure/<deployment>` | `AZURE_API_KEY` + `AZURE_API_BASE` | |
| Kimi for Coding | `kimi/kimi-for-coding` | `KIMI_API_KEY` | Spoof claude-code headers |
| OpenRouter | `openrouter/*` | `OPENROUTER_API_KEY` | 200+ models |
| Groq | `groq/*` | `GROQ_API_KEY` | |
| Mistral | `mistral/*` | `MISTRAL_API_KEY` | |
| xAI (Grok) | `xai/*` | `XAI_API_KEY` | |
| Together AI | `together_ai/*` | `TOGETHERAI_API_KEY` | |
| Ollama | `ollama/*` | none | Local models |

---

## Complete Tool Reference

### File Operations

| Tool | File | Description |
|------|------|-------------|
| `read_file` | `tools/read_file.py` | Read file contents, optional line range |
| `write_file` | `tools/write_file.py` | Create or overwrite a file |
| `edit_file` | `tools/edit_file.py` | Targeted old→new string replacement |
| `list_dir` | `tools/list_dir.py` | Directory listing with metadata |
| `glob_files` | `tools/glob_files.py` | Find files by glob pattern |
| `grep_files` | `tools/grep_files.py` | Regex search across file contents |
| `apply_patch` | `tools/apply_patch.py` | Apply unified diff patches |

### Shell Execution

| Tool | File | Description |
|------|------|-------------|
| `shell` | `tools/shell.py` | Execute shell commands (PowerShell/bash/zsh) |
| `js_repl` | `tools/js_repl.py` | Execute JavaScript via Node.js |

### Web

| Tool | File | Description |
|------|------|-------------|
| `web_fetch` | `tools/web_fetch.py` | Fetch and extract content from a URL |
| `web_search` | `tools/web_search.py` | Search the web (Brave API / SerpAPI fallback) |

### Multi-Agent

| Tool | File | Description |
|------|------|-------------|
| `spawn_agent` | `tools/multi_agent/spawn_agent.py` | Spawn a sub-agent with a task |
| `assign_task` | `tools/multi_agent/assign_task.py` | Assign a task to an existing agent |
| `send_message` | `tools/multi_agent/send_message.py` | Send a message to an agent |
| `wait_agent` | `tools/multi_agent/wait_agent.py` | Block until an agent finishes |
| `list_agents` | `tools/multi_agent/list_agents.py` | List all running agent threads |
| `close_agent` | `tools/multi_agent/close_agent.py` | Terminate an agent thread |
| `resume_agent` | `tools/multi_agent/resume_agent.py` | Resume a paused agent |

### Team Management

| Tool | File | Description |
|------|------|-------------|
| `team_create` | `tools/team_tools.py` | Create a named team with shared instructions |
| `team_spawn_agent` | `tools/team_tools.py` | Spawn an agent under a team's context |
| `team_list` | `tools/team_tools.py` | List all teams |
| `team_delete` | `tools/team_tools.py` | Delete a team |

`TeamManager` lives in `core/team.py`. A `Team` dataclass holds: `name`, `description`, `instructions`, `member_ids`. Spawning a team agent prepends team instructions to the task prompt.

### Task Tracking

| Tool | File | Description |
|------|------|-------------|
| `task_create` | `tools/task_create.py` | Create a tracked async shell task |
| `task_update` | `tools/task_update.py` | Update task status or notes |
| `task_get` | `tools/task_get.py` | Get details for a single task |
| `task_list` | `tools/task_list.py` | List tasks, filterable by status |
| `task_output` | `tools/task_output.py` | Read captured stdout/stderr |
| `task_stop` | `tools/task_stop.py` | Kill a running task |

Tasks persist to SQLite via `core/task_db.py`. Workers run in `core/tasks/worker.py`. Queue in `core/tasks/queue.py`.

### Jupyter Notebooks

| Tool | File | Description |
|------|------|-------------|
| `notebook_read` | `tools/notebook_read.py` | Read .ipynb as formatted text with outputs |
| `notebook_edit` | `tools/notebook_edit.py` | Edit specific cells in a notebook |

### Git / Worktree

| Tool | File | Description |
|------|------|-------------|
| `enter_worktree` | `tools/git_worktree.py` | Create isolated git worktree branch |
| `exit_worktree` | `tools/git_worktree.py` | Merge/discard worktree and return |

### MCP

| Tool | File | Description |
|------|------|-------------|
| `mcp_list_resources` | `tools/mcp_resource_tools.py` | List resources from MCP servers |
| `mcp_read_resource` | `tools/mcp_resource_tools.py` | Read a resource by URI |
| `mcp_authenticate` | `tools/mcp_auth_tool.py` | OAuth 2.0 PKCE auth flow for MCP server |

### IDE / LSP

| Tool | File | Description |
|------|------|-------------|
| `lsp_diagnostics` | `tools/lsp_tools.py` | Get language server diagnostics |
| `lsp_hover` | `tools/lsp_tools.py` | Hover info for a symbol |
| `lsp_definition` | `tools/lsp_tools.py` | Go to definition |
| `lsp_references` | `tools/lsp_tools.py` | Find all references |
| `lsp_rename` | `tools/lsp_tools.py` | Rename a symbol project-wide |
| `ide_get_active_file` | `tools/ide_bridge.py` | Currently open file in IDE |
| `ide_get_open_files` | `tools/ide_bridge.py` | All open files in IDE |
| `ide_get_selection` | `tools/ide_bridge.py` | Current text selection |
| `ide_get_diagnostics` | `tools/ide_bridge.py` | IDE error/warning list |

### Planning & Control Flow

| Tool | File | Description |
|------|------|-------------|
| `update_plan` | `tools/update_plan.py` | Create/update visible plan checklist |
| `todo_write` | `tools/todo_write.py` | Manage todos in `.bob-todos.json` |
| `enter_plan_mode` | `tools/plan_mode.py` | Switch to read-only Plan mode |
| `exit_plan_mode` | `tools/plan_mode.py` | Return to normal mode |

### Utilities

| Tool | File | Description |
|------|------|-------------|
| `view_image` | `tools/view_image.py` | View a local image file |
| `request_user_input` | `tools/request_user_input.py` | Pause and prompt the user |
| `tool_search` | `tools/tool_search.py` | Keyword-search the tool registry |
| `sleep` | `tools/sleep_tool.py` | Pause execution N seconds |
| `cron_create` | `tools/cron_tools.py` | Schedule a recurring task |
| `cron_delete` | `tools/cron_tools.py` | Delete a scheduled task |
| `cron_list` | `tools/cron_tools.py` | List scheduled tasks |

### Computer Use (requires `feature_flags.computer_use = true`)

| Tool | File | Action |
|------|------|--------|
| `computer_use` | `tools/computer_use.py` | `screenshot`, `left_click`, `right_click`, `double_click`, `mouse_move`, `scroll`, `key`, `type`, `cursor_position` |

Screenshot pipeline: `mss` screen grab → PIL resize to 640px max width → JPEG quality 15 → base64. Result is ~5-10 KB (~2000-4000 tokens). Requires:
```
pip install mss pyautogui
```

---

## Slash Commands (60+)

Defined in `tui/slash_commands.py` as `SlashCommand(str, Enum)`.

### Model & Reasoning
| Command | Args | Description |
|---------|------|-------------|
| `/model` | filter | Open model picker; type to filter |
| `/fast` | on/off | Toggle fast inference mode |
| `/effort` | low/medium/high | Set reasoning effort |
| `/think` | [tokens] | Set thinking token budget for next turn |

### Session Management
| Command | Args | Description |
|---------|------|-------------|
| `/new` | | Start a fresh session |
| `/resume` | | Open session picker |
| `/fork` | | Fork current session to new thread |
| `/rename` | [name] | Rename current session |
| `/compact` | | Summarize history, free context |
| `/rewind` | [N] | Undo last N turns (default 1) |
| `/clear` | | Clear terminal and full context |

### Git & Code
| Command | Args | Description |
|---------|------|-------------|
| `/diff` | | Show git diff; emits `IDEShowDiffEvent` |
| `/review` | [focus] | Review current changes for issues |
| `/commit` | | Generate commit message and commit staged files |
| `/branch` | name | Create and checkout new branch |
| `/init` | | Generate AGENTS.md for current project |

### Context
| Command | Args | Description |
|---------|------|-------------|
| `/mention` | | @ file picker |
| `/context` | url/path | Add URL or file as context for next message |
| `/export` | [filename] | Export conversation to Markdown file |
| `/summary` | | Summarize what was done this session |

### Output & Style
| Command | Args | Description |
|---------|------|-------------|
| `/output-style` | brief/normal/verbose | Response verbosity |
| `/brief` | | Alias: output-style brief |
| `/personality` | | Choose communication style |
| `/theme` | | Syntax highlight theme picker |
| `/statusline` | | Configure status line items |
| `/title` | | Configure terminal title items |

### Multi-Agent
| Command | Args | Description |
|---------|------|-------------|
| `/agent` | | Switch active agent thread |
| `/subagents` | | Manage agent threads |
| `/collab` | | Change collaboration mode |

### Tools & Extensions
| Command | Args | Description |
|---------|------|-------------|
| `/skills` | | Browse/activate skills |
| `/hooks` | | List configured hooks |
| `/mcp` | | List MCP tools from connected servers |
| `/apps` | | Manage apps |
| `/plugins` | | Browse/install plugins |

### Info & Debug
| Command | Args | Description |
|---------|------|-------------|
| `/status` | | Model, session ID, token usage |
| `/cost` | | Estimated token cost this session |
| `/usage` | | Token breakdown for last turn |
| `/ps` | | List background terminals |
| `/stop` | | Stop all background terminals |
| `/doctor` | | System health checks |
| `/debug-config` | | Show config layers and sources |
| `/rollout` | | Print rollout file path |
| `/help` | | All available commands |

### Approvals & Sandbox
| Command | Args | Description |
|---------|------|-------------|
| `/approvals` | | Configure approval policy |
| `/permissions` | | Alias for approvals |
| `/setup-default-sandbox` | | Set up elevated sandbox |
| `/sandbox-add-read-dir` | path | Allow sandbox to read a path |
| `/experimental` | | Toggle experimental features |

### Planning
| Command | Args | Description |
|---------|------|-------------|
| `/plan` | | Enter Plan mode (read-only tools only) |

### Tasks
| Command | Args | Description |
|---------|------|-------------|
| `/tasks` | [status] | List tasks (all/running/done/failed) |

### Input
| Command | Args | Description |
|---------|------|-------------|
| `/vi` | | Toggle vi keybinding mode |

### Other
| Command | Args | Description |
|---------|------|-------------|
| `/realtime` | | Toggle voice/realtime mode (experimental) |
| `/settings` | | Configure microphone/speaker |
| `/feedback` | | Send logs to maintainers |
| `/logout` | | Log out |
| `/debug-m-drop` | | Drop all memories (debug) |
| `/debug-m-update` | | Force memory update (debug) |
| `/quit` / `/exit` | | Exit bob |

**Available during active turn** (subset usable while model is running):
`/diff`, `/copy`, `/rename`, `/mention`, `/skills`, `/status`, `/debug-config`, `/ps`, `/stop`, `/mcp`, `/apps`, `/plugins`, `/feedback`, `/quit`, `/exit`, `/rollout`, `/realtime`, `/settings`, `/collab`, `/agent`, `/subagents`

---

## TUI Interface

All TUI logic in `tui/interface.py`. Built on `prompt_toolkit`.

### Screen Layout

```
┌────────────────────────────────────────────────────┐
│  Welcome banner (startup only)                      │
│    System info: model · workspace · directory       │
│    ASCII art logo                                   │
│    Recent Activity (last 3 git commits)             │
│    Quick Commands panel                             │
├────────────────────────────────────────────────────┤
│  Conversation history (scrollable)                  │
│    • User turns                                     │
│    • Assistant streaming text (live delta)          │
│    • Tool call results                              │
│    • Reasoning/thinking blocks                      │
│    • Error messages with source file:line context   │
├────────────────────────────────────────────────────┤
│  Spinner + active tool label (while running)        │
│    "● Thinking…" / "● Running shell…"               │
│    "🌐 Searching…" / "🌐 Fetching…"                 │
├────────────────────────────────────────────────────┤
│  ❯ Input prompt                                     │
│    Tab: slash command autocomplete                  │
│    @: file mention autocomplete                    │
│    Up/Down: input history                           │
│    Vi mode: toggle with /vi                         │
├────────────────────────────────────────────────────┤
│  Status line                                        │
│    model · N in  N out · $cost · N% ctx · Nms      │
└────────────────────────────────────────────────────┘
```

### Key Bindings

| Key | Action |
|-----|--------|
| `Enter` | Submit message |
| `Tab` | Autocomplete slash command or @ mention |
| `Up / Down` | Input history navigation |
| `Ctrl+V` / right-click | Paste text or clipboard image |
| `Ctrl+C` | Interrupt running turn |
| `Ctrl+C` (idle, twice) | Exit |
| `Ctrl+R` | Reverse history search |
| `Escape` | Cancel autocomplete |
| `!cmd` prefix | Direct shell passthrough |

### Clipboard Image Paste

Uses `Keys.BracketedPaste` (terminal bracketed paste mode, fired by Ctrl+V and right-click):

1. Pasted text ends with image extension + path exists → inserts `@/path/to/image`
2. Paste is empty (clipboard held an image) → runs platform clipboard reader:
   - **Windows**: `PowerShell Get-Clipboard -Format Image` → PNG to temp file
   - **macOS**: `osascript` → PNG to temp file
   - **Linux**: `xclip -selection clipboard -t image/png` or `wl-paste --type image/png`
3. Image found → saves to `%TEMP%/bob_paste_XXXX.png`, inserts `@path`
4. Otherwise → inserts pasted text normally

### Autocomplete

Slash commands: fuzzy-matched via `rapidfuzz`. Prefix matches scored higher than fuzzy matches.

File mentions: triggered by `@`. Scans cwd using glob. Shows filename + relative path.

### Status Line

After every completed turn:
```
kimi/kimi-for-coding  ·  7,199 in  46 out  ·  $0.0021  ·  1% ctx  ·  2657ms
```

Configurable items: model, tokens, cost, context %, latency. Configure with `/statusline`.

### Approval Prompt

Interrupts any turn requiring shell approval:
```
  Approval required
  Command: $ rm -rf ./dist
  CWD:     /project

  y approve   a approve-all   n reject   d abort turn
```

---

## Config System

### File location
- **Windows**: `%USERPROFILE%\.bob\config.toml`
- **macOS/Linux**: `~/.bob/config.toml`

### Full Schema (`config/schema.py`)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `model` | str | `gpt-5.1-codex-mini` | Active model |
| `api_key` | str | None | Global fallback API key |
| `base_url` | str | `https://api.openai.com/v1` | Global base URL |
| `providers` | dict | {} | Per-provider config |
| `prompt_caching` | bool | true | Anthropic `cache_control` headers |
| `reasoning_effort` | enum | medium | low / medium / high |
| `thinking_budget_tokens` | int | 0 | Extended thinking (0=off) |
| `personality` | enum | pragmatic | Communication style |
| `output_style` | enum | normal | brief / normal / verbose |
| `ask_for_approval` | enum | unless-trusted | never / unless-trusted / on-request |
| `trusted_commands` | list | [] | Shell command patterns never requiring approval |
| `sandbox_mode` | enum | workspace-write | disabled / workspace-write / workspace-write-no-exec |
| `network_proxy` | str | "" | HTTP proxy for all outbound requests |
| `web_search_mode` | enum | disabled | disabled / auto / always |
| `mcp_servers` | dict | {} | MCP server definitions |
| `mcp_auth_tokens` | dict | {} | Per-server OAuth tokens |
| `hooks` | list | [] | Event hook definitions |
| `max_context_turns` | int | 50 | Rolling history window |
| `auto_compact_threshold_tokens` | int | 0 | Auto-compact trigger token count |
| `enable_reactive_compaction` | bool | true | Mid-stream compaction on overflow |
| `enable_mid_turn_compaction` | bool | true | Compact during tool-heavy turns |
| `compact_max_retries` | int | 3 | Max compact+retry attempts per turn |
| `persist_sessions` | bool | true | Save sessions to SQLite |
| `rollout_dir` | path | None | Override rollout DB directory |
| `enable_skills` | bool | true | Auto-discover .md skill files |
| `skill_paths` | list | [] | Extra skill search directories |
| `enable_memories` | bool | true | Per-project memory system |
| `memories_path` | path | None | Override memories directory |
| `feature_flags` | dict | {} | Named experimental feature toggles |
| `no_color` | bool | false | Disable ANSI colors |
| `theme` | str | dark | Syntax highlight theme |
| `show_token_usage` | bool | false | Show after each turn |
| `show_cost` | bool | false | Show cost after each turn |
| `stream_responses` | bool | true | Live streaming vs fully-buffered |
| `exec_timeout_seconds` | int | 120 | Shell command timeout |
| `shell` | str | None | Override default shell |
| `patch_preview_lines` | int | 20 | Max diff lines in approval prompt |
| `windows_sandbox_level` | enum | disabled | Windows Job Object sandbox level |

### ProviderConfig fields

```toml
[providers.kimi]
api_key = "sk-kimi-..."           # API key
base_url = "..."                  # Override base URL
headers = { X-My-Header = "..." } # Extra HTTP headers → extra_headers kwarg
env = { MY_VAR = "value" }        # Env vars set during API calls
extra_kwargs = { timeout = 30 }   # Arbitrary LiteLLM kwargs
```

### Config loading order (later wins)

1. `BobConfig` Pydantic defaults
2. `~/.bob/config.toml`
3. `./bob.toml` in cwd
4. `AGENTS.md` workspace overrides
5. CLI flags (`--model`, `--sandbox`, `--approval`)
6. Environment variables (`OPENAI_API_KEY`, `KIMI_API_KEY`, etc.)

---

## Sandbox System

### Modes

| Mode | What it allows |
|------|---------------|
| `disabled` | Unrestricted |
| `workspace-write` | Write inside cwd; reads anywhere |
| `workspace-write-no-exec` | Write inside cwd; no external binary exec |

### Platform Implementations

**Windows** (`sandbox/windows.py`):
- `WindowsJobObject` class using ctypes (no pywin32 required)
- `CreateJobObjectW` → `SetInformationJobObject(KILL_ON_JOB_CLOSE | ACTIVE_PROCESS_LIMIT=32)`
- `AssignProcessToJobObject` called in `core/exec.py` after each subprocess spawn
- All child processes killed when job object is closed (session exit)

**macOS** (`sandbox/macos.py`):
- `sandbox-exec` with generated Scheme policy file
- Allows `file-write*` only inside cwd

**Linux** (`sandbox/linux.py`):
- `bwrap` (bubblewrap) with bind mounts
- `--ro-bind / /` + `--bind CWD CWD`

---

## Context Management

### Rolling History (`core/context_manager.py`)

Maintains list of conversation items with per-item token estimates. Drops oldest turns when over `max_context_turns`.

### Compaction (`core/compact.py`)

Triggered by:
1. `/compact` (manual)
2. `auto_compact_threshold_tokens` exceeded
3. `enable_reactive_compaction` — fires in `_stream_once` on context overflow error
4. `enable_mid_turn_compaction` — fires mid-turn when tool results push near limit

Compaction flow:
1. Send history to LLM: "Summarize this conversation preserving all technical details"
2. Replace full history with `[SUMMARY: ...]` + most-recent N turns
3. Retry original turn with compacted context

### Budget math (`core/context_budget.py`)

```
effective_limit = model_context_window × 0.85
compact_trigger = effective_limit - 8000
```

---

## MCP (Model Context Protocol)

### Connection flow

```
McpManager.start()
  └─ for each mcp_servers entry:
      └─ McpClient.connect()
          ├─ spawn subprocess (stdio transport)
          ├─ mcp.ClientSession.initialize()
          ├─ list_tools() → register each as ToolRegistry entry
          └─ list_resources() → store as McpResource list
```

### McpResource dataclass

```python
@dataclass
class McpResource:
    uri: str
    name: str
    description: str
    mime_type: str
    server_name: str
```

### MCP OAuth (`mcp/oauth.py`)

1. `_pkce_pair()` → SHA256 code verifier + base64url challenge
2. Open browser to `{authorization_url}?code_challenge=...&state=...`
3. `_wait_for_callback(state)` → asyncio HTTP server on port 7890, waits for redirect
4. `_exchange_code(code, verifier)` → POST to token endpoint
5. Token saved to `config.mcp_auth_tokens[server_name]` + `~/.bob/config.toml`

### Config example

```toml
[mcp_servers.filesystem]
command = ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/home/user"]

[mcp_servers.github]
command = ["npx", "-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_TOKEN = "ghp_..." }
```

---

## Plugin System

`plugins/manager.py` — manages `~/.bob/plugins/`

Each plugin is a directory with `plugin.json`:
```json
{ "name": "my-plugin", "version": "1.0.0", "description": "...", "enabled": true }
```

### Registry format (remote JSON)

```json
[
  { "name": "plugin-name", "version": "1.0.0", "description": "...", "url": "https://..." }
]
```

### Install sources

- Local path: `bob plugin install ./my-plugin`
- URL (zip): `bob plugin install https://example.com/plugin.zip`
- Registry: `bob plugin install my-plugin` (looks up `DEFAULT_REGISTRY_URL`)

---

## Skills System

Skills are Markdown files in `~/.bob/skills/` or `.bob/skills/` (workspace).

### Frontmatter format

```yaml
---
name: code-review
description: Focused code review skill
triggers: [review, analyze, check]
---
When reviewing code, focus on: security, performance, readability...
```

Active skill content is appended to the system prompt. Activate with `/skills`.

---

## Hooks System

`hooks/` — shell commands triggered on session events.

### Config

```toml
[[hooks]]
event = "pre_tool_call"
command = "echo tool: $BOB_TOOL_NAME"
match_tool = "shell"
timeout_seconds = 5
blocking = false

[[hooks]]
event = "session_start"
command = "./scripts/on-start.sh"
blocking = true
timeout_seconds = 10
```

### Available events

`session_start`, `session_end`, `turn_start`, `turn_end`, `pre_tool_call`, `post_tool_call`, `user_message`

---

## Analytics

`analytics/db.py` — SQLite at `~/.bob/analytics.db`

Tracks per turn:
- Session ID, timestamp
- Model, provider
- Input tokens, output tokens, cached tokens, cost
- Latency
- Tool names called

`analytics/tracker.py` — event collector during turn, batch-writes on completion.

---

## App Server (JSON-RPC 2.0)

`app_server/server.py` — WebSocket (`--port 8765`) or stdio (`--stdio`) transport.

Used by IDE extensions (VS Code, JetBrains) to communicate with bob.

### Routes

| Prefix | File | Purpose |
|--------|------|---------|
| `agents/` | `routes/agents.py` | Agent thread management |
| `config/` | `routes/config.py` | Read/write config values |
| `exec/` | `routes/exec.py` | Non-interactive execution |
| `files/` | `routes/files.py` | File operations |
| `tasks/` | `routes/tasks.py` | Task tracking CRUD |
| `threads/` | `routes/threads.py` | Session/thread management |
| `turns/` | `routes/turns.py` | Submit turns, stream events |
| `review/` | `routes/review.py` | Code review trigger |
| `realtime/` | `routes/realtime.py` | Voice/realtime mode |
| `dynamic_tools/` | `routes/dynamic_tools.py` | Register tools at runtime |

### Protocol Events (`protocol/events.py`)

| Event | Description |
|-------|-------------|
| `TextDeltaEvent` | Streaming text chunk from model |
| `ReasoningDeltaEvent` | Thinking/reasoning chunk |
| `ToolCallEvent` | Model invoked a tool (name + input) |
| `ToolResultEvent` | Tool returned a result |
| `TurnCompleteEvent` | Turn finished with usage stats |
| `ErrorEvent` | Error during turn |
| `ApprovalRequestEvent` | Shell command needs user approval |
| `IDEShowDiffEvent` | Signal IDE to open diff view |
| `StreamErrorEvent` | Transient streaming error (retry info) |

---

## Session Persistence (Rollout)

SQLite at `~/.bob/rollouts/rollout.db` (or `rollout_dir` config).

Each session stores:
- UUID session ID + title
- cwd, model at creation
- Full conversation history (JSON blob)
- Creation time + last-active time
- Activity metadata (tool call counts, etc.)

`/resume` → loads picker from DB sorted by last-active.
`bob exec --last` → queries most-recent session.
`bob exec --resume SESSION_ID` → direct resume.

---

## Memory System

Per-project persistent memory at `~/.bob/memories/` (or `memories_path`).

Each memory is a `.md` file with YAML frontmatter:
```yaml
---
name: project-context
description: Core project architecture decisions
type: project
---
This project uses FastAPI + SQLite. Auth is JWT-based.
```

`MEMORY.md` in the memories directory is an index — loaded at session start as additional context.

Types: `user`, `feedback`, `project`, `reference`.

---

## Feature Flags

Set in `config.toml`:
```toml
[feature_flags]
computer_use = true     # Enable computer_use tool
```

| Flag | Effect |
|------|--------|
| `computer_use` | Registers `computer_use` tool with full GUI automation schema |

---

## Network Proxy

```toml
network_proxy = "http://proxy.corp:8080"
```

Applied as:
- `HTTP_PROXY` + `HTTPS_PROXY` env vars during LiteLLM API calls
- `proxies=` kwarg in `httpx.AsyncClient` for `web_fetch`
- `proxy=` arg for `web_search` provider calls

---

## Cross-Platform Notes

| Feature | Windows | macOS | Linux |
|---------|---------|-------|-------|
| Default shell | PowerShell / cmd.exe | zsh | bash |
| Sandbox backend | Job Objects (ctypes) | `sandbox-exec` | `bwrap` |
| Clipboard image | `Get-Clipboard -Format Image` | `osascript` | `xclip` / `wl-paste` |
| Config dir | `%USERPROFILE%\.bob\` | `~/.bob/` | `~/.bob/` |
| UTF-8 mode | Re-exec with `-X utf8` on startup | Native UTF-8 | Native UTF-8 |
| Path separator | `\` (normalized to `/` internally) | `/` | `/` |
| bob executable | `Scripts\bob.exe` | `bin/bob` | `bin/bob` |

---

## Directory Structure

```
bob_v2_new_code_geb/
├── BOB_PLAN.md                   ← this file (full technical reference)
├── bobV2/
│   ├── README.md                 ← setup & usage guide
│   ├── pyproject.toml            ← package definition, dependencies
│   └── bob/
│       ├── __main__.py           ← python -m bob entry point
│       ├── analytics/
│       │   ├── db.py             ← SQLite analytics store
│       │   └── tracker.py        ← per-turn event collector
│       ├── app_server/
│       │   ├── server.py         ← JSON-RPC 2.0 WebSocket/stdio server
│       │   ├── router.py         ← route dispatcher
│       │   ├── schemas.py        ← request/response Pydantic models
│       │   └── routes/           ← agents, config, exec, files, tasks, turns, ...
│       ├── cli/
│       │   ├── main.py           ← typer app (bob, exec, app-server, config, mcp, plugin)
│       │   └── exec_cmd.py       ← headless non-interactive runner
│       ├── client/
│       │   └── openai_client.py  ← BobClient (OpenAI Responses API, tool streaming)
│       ├── config/
│       │   ├── schema.py         ← BobConfig Pydantic model (full settings)
│       │   ├── loader.py         ← config loading + env var merge
│       │   ├── editor.py         ← bob config set/get/unset/list (dot-notation)
│       │   └── theme.py          ← syntax theme definitions
│       ├── core/
│       │   ├── session.py        ← BobSession: orchestrator, tool registration, client init
│       │   ├── turn.py           ← single turn: stream → tool dispatch → persist
│       │   ├── context_manager.py← rolling history, token budget tracking
│       │   ├── compact.py        ← context compaction (manual + auto + reactive)
│       │   ├── context_budget.py ← token math helpers
│       │   ├── exec.py           ← subprocess creation + sandbox assignment
│       │   ├── exec_policy.py    ← approval policy evaluation
│       │   ├── network_policy.py ← network domain approval
│       │   ├── team.py           ← TeamManager, Team dataclass
│       │   ├── thread_manager.py ← multi-agent thread lifecycle
│       │   ├── tool_orchestrator.py ← parallel tool dispatch
│       │   ├── agents/
│       │   │   ├── manager.py    ← AgentManager
│       │   │   ├── supervisor.py ← DAG parallel supervisor
│       │   │   └── modes.py      ← collaboration modes
│       │   └── tasks/
│       │       ├── worker.py     ← async task worker
│       │       ├── queue.py      ← task queue
│       │       ├── models.py     ← Task dataclass
│       │       ├── executors.py  ← task executors
│       │       └── scheduler.py  ← cron scheduler
│       ├── hooks/                ← hook runner (pre/post tool, session events)
│       ├── instructions/
│       │   └── loader.py         ← system prompt builder, /init AGENTS.md generator
│       ├── llm/
│       │   ├── client.py         ← LiteLLMClient: streaming, tool normalization, sanitization
│       │   ├── compatibility.py  ← ProviderProfile, routing, auth resolution, Kimi support
│       │   └── catalog.py        ← model catalog (capabilities DB)
│       ├── mcp/
│       │   ├── client.py         ← McpClient (tools + resources, stdio transport)
│       │   ├── manager.py        ← McpManager (multi-server orchestration)
│       │   └── oauth.py          ← PKCE OAuth 2.0 flow for MCP auth
│       ├── memories/             ← per-project memory read/write
│       ├── migrations/           ← SQLite schema migrations
│       ├── plugins/
│       │   └── manager.py        ← PluginsManager (install/uninstall/registry/search)
│       ├── protocol/
│       │   ├── events.py         ← all event types incl. IDEShowDiffEvent (Pydantic)
│       │   ├── ops.py            ← operation types (UserTurnOp, OverrideTurnContextOp, ...)
│       │   └── items.py          ← content item types (TextUserInput, ImageUserInput, ...)
│       ├── rollout/              ← session persistence (SQLite rollout.db)
│       ├── sandbox/
│       │   ├── base.py           ← SandboxRunner ABC
│       │   ├── windows.py        ← WindowsSandbox + WindowsJobObject (ctypes)
│       │   ├── macos.py          ← MacOSSandbox (sandbox-exec)
│       │   └── linux.py          ← LinuxSandbox (bwrap)
│       ├── skills/               ← SkillManager, skill discovery + loading
│       ├── tools/
│       │   ├── registry.py       ← ToolRegistry: register/dispatch/search/validate
│       │   ├── computer_use.py   ← screenshot+GUI automation (mss + pyautogui)
│       │   ├── multi_agent/      ← spawn/assign/send/wait/list/close/resume agents
│       │   ├── team_tools.py     ← team_create/spawn/list/delete
│       │   ├── mcp_resource_tools.py ← mcp_list_resources, mcp_read_resource
│       │   ├── mcp_auth_tool.py  ← mcp_authenticate (PKCE OAuth)
│       │   ├── read_file.py      ← file reader with line range support
│       │   ├── write_file.py     ← full file write/create
│       │   ├── edit_file.py      ← targeted string replacement
│       │   ├── shell.py          ← shell execution + streaming output
│       │   ├── web_fetch.py      ← URL fetch + content extraction
│       │   ├── web_search.py     ← web search (Brave/SerpAPI)
│       │   ├── task_*.py         ← task create/update/get/list/output/stop
│       │   ├── cron_tools.py     ← cron_create/delete/list
│       │   └── ...               ← all other tool handlers
│       └── tui/
│           ├── interface.py      ← prompt_toolkit TUI: layout, key bindings, rendering
│           └── slash_commands.py ← SlashCommand enum, COMMAND_DESCRIPTIONS, fuzzy_match_commands
```
