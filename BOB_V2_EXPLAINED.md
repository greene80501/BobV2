# Bob v2 Explained

This document explains the current `Bob v2` codebase in this repository as of `2026-05-02`.
It is based on direct inspection of the implementation, not just the existing README text.

## 1. What Bob v2 Is

Bob v2 is a terminal-first AI coding system.

At the product level, it is:

- A CLI coding assistant you run locally with `bob`
- An interactive terminal UI for chat, approvals, planning, and code work
- A non-interactive automation runner with `bob exec`
- A JSON-RPC app server for IDEs and external clients
- A tool-executing agent that can read files, edit code, run shell commands, search code, browse the web, and control Chrome through an extension
- A multi-agent system that can spawn background workers
- A platform for MCP servers, skills, plugins, dynamic tools, and task execution

The repo positions Bob v2 as more than "chat in a terminal". It is an execution-oriented coding runtime that keeps session state, manages tools, enforces approvals/sandbox policy, and exposes itself to other applications.

Core entry points:

- CLI launcher: [`bobV2/bob/cli/main.py`](bobV2/bob/cli/main.py)
- Python module entry: [`bobV2/bob/__main__.py`](bobV2/bob/__main__.py)
- Core session runtime: [`bobV2/bob/core/session.py`](bobV2/bob/core/session.py)
- Turn execution loop: [`bobV2/bob/core/turn.py`](bobV2/bob/core/turn.py)

## 2. Why Bob v2 Exists

Bob v2 exists to turn an LLM into a usable software engineering runtime instead of a plain chatbot.

The codebase shows a few clear design goals:

1. Keep the AI inside the developer workflow, not outside it.
2. Let the model act through tools, not only answer questions.
3. Support multiple model providers instead of being tied to one backend.
4. Add durable state: sessions, rollouts, analytics, tasks, agents, plugins.
5. Make the system embeddable through an app server and browser bridge.
6. Add guardrails: approvals, network prompts, tool policies, sandbox modes, and command trust rules.

In short: Bob v2 is the "agent runtime" version of Bob, not just the first-generation terminal assistant.

## 3. What Bob v2 Does

From the current codebase, Bob v2 can:

- Run as an interactive TUI chat assistant
- Run one-shot or scripted jobs with `bob exec`
- Read, write, edit, glob, grep, and inspect project files
- Run shell commands with approval and sandbox checks
- Track sessions across restarts
- Resume, fork, compact, rewind, and rename threads
- Stream model output and reasoning in real time
- Route across many LLM providers
- Search the web and fetch URLs
- Control Chrome through a local extension bridge
- Read notebooks, edit notebooks, and view images
- Discover and use local skills
- Load plugins
- Connect to MCP servers and expose their tools
- Spawn background sub-agents, optionally in isolated git worktrees
- Run background tasks and cron-style scheduled jobs
- Expose a JSON-RPC app server for IDE or external integrations
- Publish realtime events to subscribers
- Track token usage, latency, cost, compaction, approvals, and tool activity
- Persist rollout logs and SQLite state

Important user-facing docs already in the repo:

- Root overview: [`README.md`](README.md)
- End-user CLI README: [`bobV2/README.md`](bobV2/README.md)

## 4. Languages and Tech Stack

### Primary languages

- Python 3.11+ for the Bob v2 product runtime
- JavaScript for the Chrome extension
- HTML for the Chrome side panel UI
- SQL for migrations / persisted app data
- TOML / JSON / Markdown for config, manifests, schemas, prompts, and docs

### Codebase footprint in this repo

Current snapshot:

- `166` Python source files under [`bobV2/bob/`](bobV2/bob/)
- `34` Python test files under [`bobV2/tests/`](bobV2/tests/)
- `4` Chrome extension files under [`chrome_extension/`](chrome_extension/)

### Main Python libraries

Declared in [`bobV2/pyproject.toml`](bobV2/pyproject.toml):

- `typer` for the CLI
- `prompt_toolkit` and `rich` for the interactive terminal UI
- `openai` for OpenAI Responses API access
- `litellm` for multi-provider routing
- `pydantic` for config, protocol, and schema models
- `aiosqlite` and `aiofiles` for persistence
- `markdown-it-py` for markdown rendering
- `mcp` for Model Context Protocol integration
- `requests`, `beautifulsoup4`, `pypdf`, `ddgs` for fetch/search/document tooling
- `websockets` for the app server and Chrome bridge
- `watchfiles` and `rapidfuzz` for skills/watchers and fuzzy command matching

### Important detail about the UI stack

The dependency list includes `textual`, but the current main interactive interface is built around `prompt_toolkit` plus `rich`, not a Textual app shell.
See [`bobV2/bob/tui/interface.py`](bobV2/bob/tui/interface.py).

## 5. High-Level Architecture

At a high level, Bob v2 looks like this:

```text
User / IDE / App / Chrome Extension
           |
           v
       CLI / TUI / App Server
           |
           v
        BobSession
           |
           +--> Turn runner
           |      |
           |      +--> LLM client routing
           |      |      - OpenAI Responses API
           |      |      - LiteLLM multi-provider path
           |      |
           |      +--> Tool orchestration
           |             - file tools
           |             - shell
           |             - web
           |             - browser bridge
           |             - MCP tools
           |             - app/dynamic tools
           |             - agents/tasks/etc.
           |
           +--> Persistence
           |      - rollout JSONL
           |      - SQLite thread state
           |      - analytics DB
           |      - task DBs
           |      - agent run DB
           |
           +--> Skills / Plugins / MCP
           |
           +--> Multi-agent control
           |
           +--> App-server event bus / realtime
```

## 6. Startup and Runtime Flow

### CLI startup flow

Interactive CLI startup happens in [`bobV2/bob/cli/main.py`](bobV2/bob/cli/main.py):

1. Parse CLI options with Typer.
2. Load config with [`bobV2/bob/config/loader.py`](bobV2/bob/config/loader.py).
3. Create a `BobSession`.
4. Start the session.
5. Launch the terminal UI from [`bobV2/bob/tui/interface.py`](bobV2/bob/tui/interface.py).
6. Persist the last selected model on exit.

Windows-specific detail:

- [`bobV2/bob/__main__.py`](bobV2/bob/__main__.py) and the CLI file both re-exec Python with `-X utf8` on Windows to avoid `cp1252` tokenizer JSON decoding issues in LiteLLM.

### Session startup flow

`BobSession.start()` in [`bobV2/bob/core/session.py`](bobV2/bob/core/session.py):

1. Sets up persistence.
2. Starts analytics DB.
3. Loads the final system prompt.
4. Starts the main async agent loop.
5. Prewarms provider connections.
6. Starts MCP initialization in the background.
7. Starts skill discovery in the background.
8. Starts the Chrome bridge in the background.
9. Emits a `session_started` event.

### Turn execution flow

The turn runner is in [`bobV2/bob/core/turn.py`](bobV2/bob/core/turn.py).

For each user turn, Bob v2:

1. Creates a turn id and starts analytics timing.
2. Snapshots the file tree to detect changed files later.
3. Adds the user message to rolling context.
4. Builds the list of tool specs that are currently allowed.
5. Streams the model response.
6. Emits text deltas, reasoning deltas, and token-budget updates.
7. Collects any model-requested tool calls.
8. Writes assistant output and tool calls into history.
9. Executes tool calls through the `ToolOrchestrator`.
10. Appends tool outputs back into context.
11. Repeats the loop until the model stops asking for tools.
12. Ends the turn, records analytics, and stores changed-file info.

This is the core agent loop: model output -> tools -> more model output -> final answer.

## 7. The Core Runtime

### 7.1 `BobSession`

`BobSession` is the center of the system.

File:

- [`bobV2/bob/core/session.py`](bobV2/bob/core/session.py)

It owns:

- Session id / thread id
- Current working directory
- Config and environment context
- Submission queue and event queue
- Current model client
- Sandbox runner and network policy
- Tool registry
- Context manager
- Analytics tracker
- Rollout recorder and thread state DB
- Task DB
- Chrome bridge
- MCP manager
- Skills manager
- Hook runner
- Agent control

It is the real application container for a single Bob conversation thread.

### 7.2 Submission queue and event queue

Bob does not directly "call the model when the user types".
Instead it uses:

- A submission queue for incoming operations
- An event queue for output and status

That design lets Bob support:

- approvals while a turn is still running
- interrupts
- background tool output streaming
- app-server consumers
- async agent workers

### 7.3 Agent loop

The `_agent_loop()` method in [`bobV2/bob/core/session.py`](bobV2/bob/core/session.py) processes operations such as:

- user turns
- interrupts
- exec approvals
- patch approvals
- network approvals
- dynamic tool responses
- compact requests
- rename requests
- undo / rollback
- shell passthrough commands
- list/refresh MCP
- list skills

This is a major v2 characteristic: Bob is built as an operation-processing runtime, not just a synchronous request/response wrapper.

## 8. Context, Prompting, and Compaction

### Context storage

Context is managed by [`bobV2/bob/core/context_manager.py`](bobV2/bob/core/context_manager.py).

It stores history as Response-style items:

- user messages
- assistant messages
- function calls
- function call outputs

It also supports:

- trimming old tool results
- trimming old assistant messages
- dropping the last `N` user turns
- rough token estimation from JSON size

### System prompt construction

The system prompt is not a single static file.
Bob v2 builds it from layers:

1. Base prompt: [`bobV2/bob/prompts/system.md`](bobV2/bob/prompts/system.md)
2. Optional `AGENTS.md` files via [`bobV2/bob/instructions/loader.py`](bobV2/bob/instructions/loader.py)
3. Optional developer instructions from config
4. Optional developer instructions file from config
5. Environment context from [`bobV2/bob/core/environment_context.py`](bobV2/bob/core/environment_context.py)
6. Output-style directives
7. Collaboration-mode directives

This is a strong v2 architecture choice: the prompt is assembled from product defaults plus workspace-local instructions plus runtime state.

### Context compaction

Long threads are compacted through:

- budget logic: [`bobV2/bob/core/context_budget.py`](bobV2/bob/core/context_budget.py)
- compaction engine: [`bobV2/bob/core/compact.py`](bobV2/bob/core/compact.py)

Compaction works by:

1. Asking the model to create a handoff summary
2. Preserving a bounded amount of recent user history
3. Replacing older detailed history with the summary

Bob can compact:

- before a turn
- after context-overflow errors
- mid-turn if tool-heavy continuation pushes context too far

## 9. LLM Layer and Provider Routing

### Two runtime paths

Bob v2 does not use one client for every model.

It uses:

- Native OpenAI Responses API client: [`bobV2/bob/client/openai_client.py`](bobV2/bob/client/openai_client.py)
- LiteLLM multi-provider client: [`bobV2/bob/llm/client.py`](bobV2/bob/llm/client.py)

### Routing logic

Provider and model compatibility are handled in:

- [`bobV2/bob/llm/compatibility.py`](bobV2/bob/llm/compatibility.py)

Key behavior:

- `gpt-5`, `o1`, `o3`, `o4`, and codex-style OpenAI models route to native OpenAI Responses API
- Other providers route through LiteLLM chat-completions style flows
- Bare model names can be canonicalized to provider-prefixed forms like `gemini/...` or `anthropic/...`
- Provider auth is resolved from config and environment variables

### Supported providers

The compatibility matrix in code includes profiles for:

- OpenAI
- Anthropic
- Google Gemini
- Vertex AI
- Azure OpenAI
- Groq
- Mistral
- Cohere
- Together AI
- OpenRouter
- xAI
- IBM watsonx
- GLM ZAI
- Ollama
- Kimi for Coding

Not all are equally mature.
The code explicitly labels some support as:

- `stable`
- `experimental`
- `catalog_only`
- `unknown`

### Why this matters

This multi-route design is a big architectural upgrade.
Bob v2 is not a single-provider wrapper; it is a provider abstraction layer with per-model behavior.

## 10. Tool System

### Tool registry

The central registry is:

- [`bobV2/bob/tools/registry.py`](bobV2/bob/tools/registry.py)

Each tool is registered with:

- name
- description
- JSON schema
- async handler
- mutating/non-mutating flag
- parallel support flag
- network-approval flag
- source tag
- discoverability / deferred-loading metadata

### Tool orchestration

Tool execution is centralized in:

- [`bobV2/bob/core/tool_orchestrator.py`](bobV2/bob/core/tool_orchestrator.py)

The orchestrator handles:

- plan-mode blocking of mutating tools
- network approval prompts
- tool policy filtering
- parallel vs sequential execution
- shell-specific execution flow
- exec events and approval prompts

### Built-in tool categories

`BobSession._register_builtin_tools()` registers a large built-in tool surface.
Major groups include:

- File tools: `read_file`, `write_file`, `edit_file`, `glob_files`, `grep_files`, `list_dir`, `read_pdf`
- Shell and patch tools
- Planning and user-interaction tools
- Web tools: `web_search`, `web_fetch`
- Browser bridge tool
- Notebook tools
- Task tools
- LSP / IDE bridge tools
- Git worktree tools
- MCP resource/auth tools
- Skills and apps support
- Multi-agent tools
- Optional computer-use tool

Tool registration lives mainly in:

- [`bobV2/bob/core/session.py`](bobV2/bob/core/session.py)

## 11. Shell Execution, Approvals, and Safety

### Shell execution

Shell execution runs through:

- orchestration rules: [`bobV2/bob/core/tool_orchestrator.py`](bobV2/bob/core/tool_orchestrator.py)
- command execution: [`bobV2/bob/core/exec.py`](bobV2/bob/core/exec.py)

Features include:

- streamed stdout/stderr
- timeout handling
- process-group kill on timeout/cancel
- hard output caps
- Windows PowerShell wrapping for non-PowerShell commands
- event emission for start/output/end

### Approval model

Approval logic in [`bobV2/bob/core/turn.py`](bobV2/bob/core/turn.py) and [`bobV2/bob/core/tool_orchestrator.py`](bobV2/bob/core/tool_orchestrator.py) supports policies like:

- never
- unless-trusted
- on-request
- on-failure

Bob also maintains:

- built-in trusted read-only commands
- session-approved commands
- configurable trusted command patterns

### Escalation detection

The turn runtime checks for obvious escalation signals like:

- `sudo`
- `su`
- `doas`
- `chroot`
- `ptrace`
- `LD_PRELOAD`
- shell metachar injection

### Network approval

Networked tools can require per-request approval.
The orchestrator extracts the target domain and asks the user before continuing.

### Sandbox layer

Sandbox abstractions live in:

- [`bobV2/bob/sandbox/base.py`](bobV2/bob/sandbox/base.py)
- [`bobV2/bob/sandbox/windows.py`](bobV2/bob/sandbox/windows.py)
- [`bobV2/bob/sandbox/linux.py`](bobV2/bob/sandbox/linux.py)
- [`bobV2/bob/sandbox/macos.py`](bobV2/bob/sandbox/macos.py)

Important current reality on Windows:

- The Windows sandbox validates path grants and uses Job Objects for process control.
- Full restricted-token process launching is not fully implemented in the current wrapper path.

That means v2 has meaningful safety plumbing, but some platform enforcement details are still evolving.

## 12. CLI, TUI, and Non-Interactive Mode

### CLI

Main file:

- [`bobV2/bob/cli/main.py`](bobV2/bob/cli/main.py)

Main modes:

- `bob` for interactive TUI
- `bob exec` for non-interactive runs
- `bob app-server` for JSON-RPC mode
- `bob config ...`
- `bob mcp ...`
- `bob plugin ...`
- `bob export-schemas`

### TUI

Main interface:

- [`bobV2/bob/tui/interface.py`](bobV2/bob/tui/interface.py)

The TUI is responsible for:

- rendering streamed output
- approval prompts
- activity lines for tool usage
- markdown rendering
- slash command handling
- session status display

Slash command definitions live in:

- [`bobV2/bob/tui/slash_commands.py`](bobV2/bob/tui/slash_commands.py)

That file shows Bob v2 supports command families for:

- model/runtime control
- approvals and sandbox config
- session management
- planning / compacting / reviewing / diffing
- plugins / apps / MCP / skills
- analytics / token / cost display
- collaboration mode
- Chrome bridge toggle
- tasks and background process management

### Non-interactive mode

`bob exec` is implemented in:

- [`bobV2/bob/cli/exec_cmd.py`](bobV2/bob/cli/exec_cmd.py)

It supports:

- direct prompt execution
- stdin input
- JSONL event streaming
- resume-last / resume-by-id
- ephemeral sessions
- auto-approval modes
- "yolo" full-auto mode
- writing the last assistant message to a file

## 13. App Server and External Integration

### Server

The app server is in:

- [`bobV2/bob/app_server/server.py`](bobV2/bob/app_server/server.py)

It supports:

- stdio transport
- WebSocket transport
- JSON-RPC 2.0 request handling
- middleware
- event replay and subscriptions
- session/thread registry
- task runtime

### Request routing

Core router:

- [`bobV2/bob/app_server/router.py`](bobV2/bob/app_server/router.py)

Registered route groups:

- [`bobV2/bob/app_server/routes/threads.py`](bobV2/bob/app_server/routes/threads.py)
- [`bobV2/bob/app_server/routes/turns.py`](bobV2/bob/app_server/routes/turns.py)
- [`bobV2/bob/app_server/routes/files.py`](bobV2/bob/app_server/routes/files.py)
- [`bobV2/bob/app_server/routes/exec.py`](bobV2/bob/app_server/routes/exec.py)
- [`bobV2/bob/app_server/routes/dynamic_tools.py`](bobV2/bob/app_server/routes/dynamic_tools.py)
- [`bobV2/bob/app_server/routes/tasks.py`](bobV2/bob/app_server/routes/tasks.py)
- [`bobV2/bob/app_server/routes/agents.py`](bobV2/bob/app_server/routes/agents.py)
- plus `review`, `realtime`, `config`, and `legacy`

### Thread/session registry

The server-side thread registry is:

- [`bobV2/bob/app_server/registry.py`](bobV2/bob/app_server/registry.py)

It maps app-server threads to `BobSession` instances and consumes session events into thread/turn state.

### Event bus

Realtime event storage and replay live in:

- [`bobV2/bob/app_server/event_bus.py`](bobV2/bob/app_server/event_bus.py)

It:

- stores events in SQLite
- supports subscriptions by channel
- supports replay after a cursor

This makes Bob v2 much easier to integrate with editors and external apps.

### Dynamic tools

One of the more advanced v2 features is dynamic tool registration:

- [`bobV2/bob/app_server/routes/dynamic_tools.py`](bobV2/bob/app_server/routes/dynamic_tools.py)

External clients can:

- register tool descriptors at runtime
- search tools
- enable hidden/deferred tools
- respond asynchronously to dynamic tool calls

This means Bob v2 can grow its tool surface at runtime without rebuilding the core binary.

## 14. Multi-Agent System

### Core design

Multi-agent orchestration lives in:

- [`bobV2/bob/core/agents/control.py`](bobV2/bob/core/agents/control.py)

This subsystem can:

- spawn background workers
- give them specialized instructions
- optionally fork parent context
- constrain their allowed tools
- run them read-only if needed
- place them in shared workspace or isolated git worktrees
- wait for results
- message them
- persist run metadata

### Agent definitions and runtime

Important files:

- [`bobV2/bob/core/agents/runtime.py`](bobV2/bob/core/agents/runtime.py)
- [`bobV2/bob/core/agents/store.py`](bobV2/bob/core/agents/store.py)
- [`bobV2/bob/core/agents/worktree.py`](bobV2/bob/core/agents/worktree.py)
- [`bobV2/bob/tools/agents/spawn_agent.py`](bobV2/bob/tools/agents/spawn_agent.py)

### Worktree isolation

If the repo is a git repo, Bob v2 can create:

- `.bob_worktrees/<agent_id>`

for child agents.

Then it can:

1. let the worker edit in isolation
2. commit inside the worktree
3. squash-merge results back into the main tree

This is one of the clearest "v2" architecture upgrades in the repo.

### Agent persistence

Agent runs are stored in:

- `~/.bob/agent_runs.sqlite`

through [`bobV2/bob/core/agents/store.py`](bobV2/bob/core/agents/store.py).

## 15. Task Runtime

There are actually two task concepts in this codebase:

1. Simple task-management tools attached to a session task DB
2. A fuller app-server task runtime with workers and scheduling

### App-server task runtime

Main files:

- [`bobV2/bob/core/tasks/__init__.py`](bobV2/bob/core/tasks/__init__.py)
- [`bobV2/bob/core/tasks/worker.py`](bobV2/bob/core/tasks/worker.py)
- [`bobV2/bob/core/tasks/scheduler.py`](bobV2/bob/core/tasks/scheduler.py)
- [`bobV2/bob/core/tasks/executors.py`](bobV2/bob/core/tasks/executors.py)

The runtime supports:

- queued tasks
- local shell execution
- cron-triggered tasks
- event publishing
- task status persistence

Current implementation status:

- `local_shell` works
- `remote_shell` exists as `SshExecutor` but is scaffolded and not yet enabled
- cron scheduling is intentionally described in code as a minimal bootstrap implementation

## 16. Browser Bridge and Chrome Extension

### Architecture

Bob v2 includes first-party browser control.

Python side:

- bridge: [`bobV2/bob/bridge/chrome_bridge.py`](bobV2/bob/bridge/chrome_bridge.py)
- tool: [`bobV2/bob/tools/browser.py`](bobV2/bob/tools/browser.py)

Extension side:

- manifest: [`chrome_extension/manifest.json`](chrome_extension/manifest.json)
- background worker: [`chrome_extension/background.js`](chrome_extension/background.js)
- side panel UI: [`chrome_extension/sidepanel.js`](chrome_extension/sidepanel.js)

### How it works

1. Bob starts a WebSocket server on `ws://localhost:9876`.
2. The Chrome side panel connects to that socket.
3. Bob sends browser actions as JSON.
4. The extension runs the action on the active tab.
5. The extension returns text, HTML, screenshots, or action results.

### Supported browser actions

The browser tool supports actions like:

- `navigate`
- `get_page_text`
- `get_page_html`
- `screenshot`
- `click`
- `form_input`
- `type_text`
- `execute_js`
- `find_elements`
- `scroll`
- `get_current_url`

### Important product behavior

The browser tool is intentionally separate from `web_fetch`.

Use cases:

- `web_fetch` for public pages
- `browser` for authenticated sites, JS-heavy apps, or true interaction

The browser tool also tries to compress/reject screenshots that would be too large for the model context.

## 17. MCP, Skills, and Plugins

### MCP

MCP lifecycle and registration are handled in:

- [`bobV2/bob/mcp/manager.py`](bobV2/bob/mcp/manager.py)
- [`bobV2/bob/core/session.py`](bobV2/bob/core/session.py)

Bob v2 can:

- load configured MCP servers
- import MCP servers from plugin bundles
- optionally import MCP definitions from Claude settings
- register server tools into Bob's tool registry
- expose MCP resources and MCP auth flows

### Skills

Skills are managed by:

- [`bobV2/bob/skills/manager.py`](bobV2/bob/skills/manager.py)

Discovery scopes:

- `~/.bob/skills`
- `<repo>/.bob/skills`
- plugin-injected skills

Supported formats:

- Bob-native `skill.toml` + `skill.md`
- Claude/Codex-style `SKILL.md` with YAML frontmatter

### Plugins

Plugins are managed by:

- [`bobV2/bob/plugins/manager.py`](bobV2/bob/plugins/manager.py)

Supported plugin manifests include:

- `plugin.toml`
- `.claude-plugin/plugin.json`
- `.codex-plugin/plugin.json`

Plugins can also contribute:

- MCP server bundles
- skills
- remote registry-installable packages

This is another strong v2 trait: Bob is not a closed monolith.

## 18. Persistence, Rollouts, Analytics, and Memories

### Rollouts

Every non-ephemeral session can be persisted as JSONL rollout history:

- recorder: [`bobV2/bob/rollout/recorder.py`](bobV2/bob/rollout/recorder.py)

### Thread/session state

SQLite thread state is managed by:

- [`bobV2/bob/rollout/state_db.py`](bobV2/bob/rollout/state_db.py)

This stores:

- thread metadata
- path to rollout file
- model
- cwd
- preview text
- turn counts

### Analytics

Analytics stack:

- tracker: [`bobV2/bob/analytics/tracker.py`](bobV2/bob/analytics/tracker.py)
- reports: [`bobV2/bob/analytics/report.py`](bobV2/bob/analytics/report.py)
- model pricing/catalog: [`bobV2/bob/llm/catalog.py`](bobV2/bob/llm/catalog.py)

Tracked data includes:

- input/output tokens
- cached input tokens
- estimated cost
- latency
- changed files
- compaction activity
- tool durations
- approvals
- shell commands
- agent spawns/completions
- budget peaks

### Memories

Memory code lives in:

- [`bobV2/bob/memories/phase1.py`](bobV2/bob/memories/phase1.py)
- [`bobV2/bob/memories/storage.py`](bobV2/bob/memories/storage.py)

The memory system can extract useful long-term facts from rollouts and store consolidated summaries.

## 19. Configuration System

### Loader

Config loading is implemented in:

- [`bobV2/bob/config/loader.py`](bobV2/bob/config/loader.py)

### Merge order

Bob v2 merges config layers in this order:

1. built-in defaults
2. user config: `~/.bob/config.toml`
3. optional imported Claude MCP settings
4. project config found by walking upward to `.bob/config.toml`
5. CLI overrides

### Environment loading

`.env` loading is bootstrapped before config validation.
The README says Bob auto-loads project `.env` and `~/.bob/.env`.

### Config model

The full typed config is defined in:

- [`bobV2/bob/config/schema.py`](bobV2/bob/config/schema.py)

It covers:

- model/provider settings
- approval policy
- sandbox/network policy
- collaboration mode
- web search settings
- MCP server definitions
- hooks
- developer instructions
- context limits and compaction
- UI settings
- shell defaults
- skills
- memories
- persistence
- feature flags

## 20. Protocol and Schemas

Bob v2 has a structured protocol layer in:

- [`bobV2/bob/protocol/`](bobV2/bob/protocol/)
- [`bobV2/bob/protocol/v1/`](bobV2/bob/protocol/v1/)

This includes:

- operation types
- event types
- request/response models
- exported JSON Schemas

The protocol layer is what makes the same core runtime usable from:

- the terminal UI
- non-interactive CLI
- the app server
- external clients

## 21. Directory Map

Top-level repo layout:

- [`bobV2/`](bobV2/) - main Bob v2 Python project
- [`chrome_extension/`](chrome_extension/) - Chrome side-panel browser bridge
- [`bobV2/chacter/`](bobV2/chacter/) - local character art / helper assets

Important Bob v2 subdirectories:

- [`bobV2/bob/cli/`](bobV2/bob/cli/) - CLI entry points
- [`bobV2/bob/tui/`](bobV2/bob/tui/) - interactive terminal UI
- [`bobV2/bob/core/`](bobV2/bob/core/) - session, turn loop, context, exec, tasks
- [`bobV2/bob/tools/`](bobV2/bob/tools/) - built-in tool handlers
- [`bobV2/bob/client/`](bobV2/bob/client/) - native OpenAI client
- [`bobV2/bob/llm/`](bobV2/bob/llm/) - compatibility, LiteLLM client, model catalog
- [`bobV2/bob/app_server/`](bobV2/bob/app_server/) - JSON-RPC server and routes
- [`bobV2/bob/bridge/`](bobV2/bob/bridge/) - Chrome bridge
- [`bobV2/bob/mcp/`](bobV2/bob/mcp/) - MCP connection management
- [`bobV2/bob/plugins/`](bobV2/bob/plugins/) - plugin loading
- [`bobV2/bob/skills/`](bobV2/bob/skills/) - skill discovery
- [`bobV2/bob/analytics/`](bobV2/bob/analytics/) - token/cost analytics
- [`bobV2/bob/rollout/`](bobV2/bob/rollout/) - session persistence
- [`bobV2/bob/sandbox/`](bobV2/bob/sandbox/) - platform-specific sandbox wrappers
- [`bobV2/tests/`](bobV2/tests/) - unit and integration tests

## 22. Testing and Quality Signals

The test suite covers many important subsystems.

Examples from [`bobV2/tests/unit/`](bobV2/tests/unit/) and [`bobV2/tests/integration/`](bobV2/tests/integration/):

- analytics and provider inference
- agent definitions, store, and worktrees
- app-server files and dynamic tools
- browser bridge
- context budget / compaction
- dot-env loading
- grep/list-dir tools
- LiteLLM client behavior
- MCP and skills
- model compatibility
- session logging
- slash commands
- tool orchestration
- Windows sandbox policy
- web search

This test spread shows Bob v2 is being treated as a real runtime platform, not a thin demo.

## 23. What Makes This Clearly "v2"

From the current code, the clearest v2 characteristics are:

1. The runtime is modular.
   It separates CLI, session management, tool registry, provider routing, app server, agents, browser bridge, persistence, and analytics.

2. It is platform-like, not feature-like.
   Skills, plugins, MCP servers, dynamic tools, and app-server routes all extend the core.

3. It is stateful.
   Bob v2 stores sessions, rollouts, analytics, tasks, agent runs, and app events.

4. It is multi-provider by design.
   The compatibility layer and dual client routing are first-class architecture, not an afterthought.

5. It is execution-focused.
   Tools, shell access, browser control, background workers, and tasks are central.

6. It is integration-ready.
   JSON-RPC, realtime subscriptions, dynamic tool registration, and Chrome bridge support external clients.

## 24. Current Limitations and Honest Read

A few limits are visible in the current implementation:

- Windows sandboxing is partially enforced, but not a fully hardened restricted-token execution environment yet.
- `SshExecutor` is scaffolded but not active.
- Cron scheduling is intentionally minimal.
- Browser control depends on the Chrome extension being connected.
- Some provider integrations are marked experimental or catalog-only.
- Context token estimation is approximate in several places.

None of these invalidate the architecture, but they are real implementation realities worth stating.

## 25. How to Run Bob v2

From the repo:

```powershell
cd bobV2
py -3.11 -m pip install -e .
bob
```

Other useful modes:

```powershell
bob exec "explain this repo"
bob app-server --stdio
bob app-server --port 8765
```

Main install/runtime docs:

- [`bobV2/README.md`](bobV2/README.md)
- [`bobV2/.env.example`](bobV2/.env.example)

## 26. Final Summary

Bob v2 is a Python-based AI coding runtime with a terminal interface, tool execution engine, multi-provider LLM routing, persistent session model, app-server API, browser-control bridge, MCP/plugin/skill ecosystem, multi-agent execution model, and analytics/persistence infrastructure.

If you need one sentence for your team:

> Bob v2 is not just "Bob with more commands"; it is a full local agent platform for coding workflows, built around `BobSession`, tool orchestration, provider abstraction, persistent state, and external integrations.
