# Bob CLI Technical Documentation

Last reviewed: 2026-05-02

## Scope

This document describes the implemented behavior of the `bobV2/` project in this repository. It is based on the current Python code, tests, and shipped assets, not just the README.

Out of scope:

- `bobV2/graybench_audit/` is currently untracked and not wired into the Bob CLI entrypoints.
- `chacter/` is art and helper assets, not part of the Bob runtime.
- `chrome_extension/` is part of the browser-control story, but it is a companion extension rather than the CLI itself.

Primary source files for this document:

- `bob/cli/main.py`
- `bob/core/session.py`
- `bob/core/turn.py`
- `bob/core/tool_orchestrator.py`
- `bob/tui/interface.py`
- `bob/llm/compatibility.py`
- `bob/llm/client.py`
- `bob/client/openai_client.py`
- `bob/app_server/server.py` and `bob/app_server/routes/*`
- `bob/sandbox/*`
- `bob/plugins/manager.py`
- `bob/skills/manager.py`
- `bob/mcp/manager.py`

## What Bob CLI is

Bob is a terminal-first coding agent with four main runtime surfaces:

1. An interactive TUI started by `bob`
2. A non-interactive command mode started by `bob exec`
3. A JSON-RPC app server started by `bob app-server`
4. A local Chrome-extension bridge for browser control on `ws://127.0.0.1:9876`

At a high level, Bob:

- loads config and environment state
- builds a system prompt from built-in instructions plus project instructions
- routes model calls through either the OpenAI Responses API or LiteLLM
- exposes a built-in tool registry to the model
- executes tool calls under approval and sandbox policy
- persists sessions, rollouts, analytics, tasks, and logs under `~/.bob`

It is not just a chatbot shell. It is an agent runtime with session persistence, tool orchestration, app-server APIs, extensions, and background task infrastructure.

## Repository layout

Relevant top-level layout:

- `bob/cli/`: CLI entrypoints
- `bob/tui/`: interactive terminal UI
- `bob/core/`: session lifecycle, turn loop, tool orchestration, execution policy, context management
- `bob/tools/`: built-in model tools
- `bob/llm/` and `bob/client/`: model routing and provider clients
- `bob/config/`: config schema, config loading, config editing, `.env` support
- `bob/app_server/`: JSON-RPC app server and routes
- `bob/mcp/`: MCP client/server connection management
- `bob/plugins/`: plugin discovery and installation
- `bob/skills/`: skill discovery
- `bob/bridge/`: Chrome extension bridge
- `bob/rollout/`: rollout recording and session index/state DB
- `bob/analytics/`: token/cost tracking
- `bob/sandbox/`: platform-specific sandbox wrappers
- `tests/`: unit and integration coverage

## User-facing runtime surfaces

### Interactive CLI

Entry point:

- `bob` via `project.scripts` in `pyproject.toml`
- implementation in `bob/cli/main.py`

Behavior:

- launches the TUI by constructing a `BobSession` and calling `run_interface`
- supports initial prompt injection via `--prompt`
- supports model, sandbox, approval, resume-session, and working-directory overrides
- on Windows, re-execs with `-X utf8` before heavy imports to avoid `cp1252` tokenizer issues

### Non-interactive mode

Entry point:

- `bob exec`

Behavior:

- accepts prompt from CLI or stdin
- streams normal text output or JSONL event output
- can resume prior sessions
- can write the last assistant message to a file
- supports `--ephemeral`, `--last`, `--json`, `--output-last-message`

Important implementation note:

- `--yolo` really disables approvals and sandbox by setting `ask_for_approval=never` and `sandbox_mode=danger-full-access`.
- `--full-auto` is documented as auto-approving everything, but the current code sets `ask_for_approval=on-request`, which still triggers approval flow. In practice, `--full-auto` does not currently behave like a true "approve everything" mode.

### App server

Entry point:

- `bob app-server --stdio`
- `bob app-server --port 8765`

Transport:

- stdio JSON-RPC 2.0
- WebSocket JSON-RPC 2.0

Implemented RPC methods:

- `server.capabilities`
- `bob.config.get`
- `bob.models.list`
- `ping`
- `threads.create`, `threads.get`, `threads.list`
- `turns.submit`, `turns.get`, `turns.list`, `turns.interrupt`, `turns.cancel`
- `history.read`
- `files.read`, `files.write`, `files.edit`, `files.glob`, `files.grep`
- `exec.start`, `exec.wait`, `exec.terminate`
- `dynamic_tools.register`, `dynamic_tools.list`, `dynamic_tools.search`, `dynamic_tools.enable`, `dynamic_tools.respond`
- `tasks.create`, `tasks.get`, `tasks.list`, `tasks.cancel`
- `review.submit`, `review.result`
- `realtime.subscribe`, `realtime.unsubscribe`, `realtime.replay`
- legacy aliases: `bob.session.create`, `bob.session.submit`, `bob.session.interrupt`, `bob.session.shutdown`

Important limitation:

- `server.capabilities` explicitly advertises `"agents": false` even though the core session supports sub-agents. The app server does not expose an agent RPC surface.

### Browser control

Bob includes a `browser` tool backed by the local Chrome extension bridge:

- bridge server: `bob/bridge/chrome_bridge.py`
- default port: `9876`
- extension side lives under top-level `chrome_extension/`

Capabilities:

- navigate
- extract page text
- extract raw HTML
- click
- type into fields
- find elements
- scroll
- get current URL
- execute JS
- request screenshot

Important limitations:

- it requires the extension to be connected
- it keeps only one active extension connection
- Chrome internal pages such as `chrome://...` are not usable for content extraction
- screenshots are intentionally discouraged because they are large and expensive in token terms

## Slash commands

Current slash commands defined in `bob/tui/slash_commands.py`:

- `model`, `fast`, `approvals`, `permissions`, `setup-default-sandbox`, `sandbox-add-read-dir`
- `experimental`, `skills`, `review`, `rename`, `new`, `resume`, `fork`, `init`
- `compact`, `plan`, `collab`, `diff`, `copy`, `mention`, `status`, `debug-config`
- `title`, `statusline`, `theme`, `mcp`, `apps`, `plugins`, `logout`, `quit`, `exit`
- `feedback`, `rollout`, `ps`, `stop`, `clear`, `personality`, `realtime`, `settings`
- `debug-m-drop`, `debug-m-update`, `help`, `effort`, `cost`, `usage`
- `commit`, `branch`, `export`, `rewind`, `summary`, `doctor`, `context`, `output-style`
- `vi`, `hooks`, `think`, `brief`, `tasks`, `bob-in-chrome`

What they generally cover:

- model selection and reasoning controls
- session lifecycle
- git workflow helpers
- export and review helpers
- config and display controls
- skills, MCP, plugins, and browser bridge access
- task and token/cost inspection

Current implementation caveat:

- `bob/tui/interface.py` still contains stale branches referencing nonexistent enum members such as `SlashCommand.CONFIG`, `SlashCommand.STATS`, `SlashCommand.SESSION`, `SlashCommand.MEMORY`, `SlashCommand.SHARE`, `SlashCommand.ISSUE`, and `SlashCommand.PR_COMMENTS`.
- Those commands are not present in the active `SlashCommand` enum. This is code drift and should be treated as a bug risk in the TUI command dispatcher.

## Built-in model tools

Built-in tool names currently registered in a normal non-ephemeral session:

- `shell`, `update_plan`, `view_image`, `list_dir`
- `read_file`, `read_pdf`, `write_file`, `edit_file`, `glob_files`, `grep_files`
- `sleep`, `todo_write`, `enter_plan_mode`, `exit_plan_mode`
- `web_search`, `web_fetch`
- `schedule_cron`, `remote_trigger`
- `js_repl`, `notebook_read`, `notebook_edit`
- `task_create`, `task_update`, `task_list`, `task_get`, `task_output`, `task_stop`
- `request_user_input`, `tool_search`
- `enter_worktree`, `exit_worktree`
- `lsp_diagnostics`, `lsp_hover`, `lsp_definition`, `lsp_references`, `lsp_rename`
- `ide_get_open_files`, `ide_get_selection`, `ide_get_diagnostics`, `ide_get_active_file`
- `browser`
- `mcp_authenticate`
- `spawn_agent`, `wait_agent`, `send_message`, `assign_task`, `close_agent`, `list_agents`
- `mcp_list_resources`, `mcp_read_resource`

Conditionally available tools:

- `web_search` is omitted if `web_search_mode=disabled`
- `computer_use` exists in code but is only registered when explicitly enabled by feature flag
- agent tools are not registered for ephemeral sessions
- plugin/MCP/app/dynamic tools can be added later at runtime

Tool categories:

### Files and local workspace

- read directory trees, files, PDFs, notebooks, and images
- write and edit files
- glob and grep across the repo
- perform LSP and IDE-backed code inspection

### Execution

- `shell` is the general execution primitive
- `js_repl` is a JavaScript execution helper
- worktree tools support git worktree workflows

### Planning and control

- `update_plan`
- plan-mode entry and exit
- `todo_write`
- `request_user_input`
- `tool_search`

### Network and browser

- `web_search`
- `web_fetch`
- `browser`
- MCP auth and resources

### Scheduling and tasks

- cron scheduling stored in `~/.bob/schedules.db`
- a simple SQLite-backed task tracker via `task_*`

### Multi-agent

- spawn sub-agents
- message them
- wait for completion
- close them
- inspect running agents

## Configuration model

Bob config is defined in `bob/config/schema.py` and loaded in four layers:

1. built-in defaults
2. user config at `~/.bob/config.toml`
3. project config found by walking upward to `.bob/config.toml`
4. CLI overrides

`.env` loading:

- Bob auto-loads `.env` files before config resolution
- supported locations include the project root and `~/.bob/.env`

Major config areas:

- model and provider config
- reasoning effort and thinking budget
- personality and output style
- approvals and trusted commands
- sandbox mode and writable roots
- network access and approved domains
- web-search config
- MCP servers and imported Claude settings
- hooks
- developer instructions and AGENTS.md inclusion
- context and compaction budgets
- UI behavior
- shell defaults
- skills, memories, rollout persistence
- feature flags

Defaults worth noting:

- model: `gpt-5.1-codex-mini`
- sandbox: `workspace-write`
- network access: `true`
- web search mode: `live`
- session persistence: enabled
- memories: enabled

## Model and provider routing

Provider routing is handled by `bob/llm/compatibility.py`.

The central decision is whether a model goes through:

- OpenAI Responses API (`bob/client/openai_client.py`)
- LiteLLM chat-completions compatibility layer (`bob/llm/client.py`)

Current routing rules:

- OpenAI GPT-5, o1, o3, o4, and codex-family models use the native OpenAI Responses route
- most other providers use LiteLLM
- bare Gemini names are normalized to `gemini/<model>`
- Kimi is routed through an OpenAI-compatible path with a default Kimi base URL

Supported provider families in the compatibility matrix include:

- OpenAI
- Anthropic
- Gemini
- Vertex AI
- Azure OpenAI
- Groq
- Mistral
- Cohere
- Together AI
- OpenRouter
- xAI
- Ollama
- Kimi
- best-effort catalog-only providers such as IBM watsonx and GLM ZAI

Auth resolution behavior:

- provider-specific config wins
- then provider-specific environment variables
- then global fallback `api_key` or `BOB_API_KEY`
- special provider env requirements are enforced for Vertex AI

Request-parameter mapping:

- OpenAI Responses route maps `reasoning_effort` into `reasoning.effort`
- LiteLLM route maps prompt caching, thinking budget, reasoning effort, and service tier when supported by the provider profile

## How Bob builds the system prompt

`BobSession._load_system_prompt()` composes the prompt from:

1. built-in prompt markdown from `bob/prompts/system.md`
2. concatenated `AGENTS.md` files from global and workspace hierarchy
3. inline `developer_instructions`
4. optional `developer_instructions_file`
5. an environment block from `EnvironmentContext.build()`
6. output-style directives
7. collaboration-mode directives

The environment block includes:

- OS and shell
- cwd and home
- UTC timestamp
- git branch and dirty/clean summary
- a shallow workspace snapshot
- special Windows command guidance

This means Bob is intentionally prompt-primed with local execution context before the first turn.

## Session lifecycle and turn execution

The core runtime type is `BobSession`.

Session startup performs:

- persistence setup
- analytics DB setup
- system prompt load
- background session agent loop launch
- connection prewarm for compatible OpenAI routes
- background startup for MCP, skills, and Chrome bridge
- emission of `session_started`

Each user turn goes through `run_turn()` in `bob/core/turn.py`:

1. emit `turn_started`
2. snapshot workspace file metadata for changed-file analytics
3. convert user items into Responses-API-style history entries
4. stream model output
5. accumulate assistant text, reasoning deltas, and tool calls
6. append response items to history
7. execute tool calls through the orchestrator
8. append tool results to history
9. repeat until the model stops calling tools
10. emit `turn_ended` and finalize analytics

Important turn mechanics:

- history is stored in a Responses-style item list, not plain chat strings
- interrupted/orphaned tool calls are patched with placeholder outputs to avoid API consistency failures
- only non-mutating and parallel-safe tools are run concurrently
- tool-heavy turns can trigger mid-turn compaction
- context overflow can trigger auto-recovery and retry
- max per-turn tool/model loop iterations: `50`

## Tool orchestration

`ToolOrchestrator` is the central execution path for tool calls.

It performs, in order:

1. plan-mode filtering
2. network-approval filtering
3. allowed-tool/read-only policy filtering
4. parallel vs sequential partitioning
5. execution and event emission

Parallelism rule:

- only non-mutating tools marked `supports_parallel=True` are run in parallel
- mutating tools are serialized

Shell execution behavior:

- `shell` is special-cased to emit exec lifecycle events
- `apply_patch` is intercepted and executed via Bob's Python patcher instead of the OS shell
- Windows `dir /s /b` is normalized into `Get-ChildItem -Recurse -Name`
- commands can be denied, approved once, approved for session, or abort the turn

## Context management and compaction

History lives in `ContextManager`.

Capabilities:

- append and replace raw history items
- remove oldest items
- trim old assistant messages and old tool outputs
- undo last `N` user turns
- estimate token size by JSON-length heuristic

Compaction behavior:

- compaction is model-generated, not rule-based summarization
- the summary is written back into history as a synthetic user message
- Bob keeps recent user messages plus a compaction summary
- compaction can run manually, pre-turn, mid-turn, or as recovery from provider context-window errors
- Bob warns that repeated compactions can reduce answer quality

## Approvals, safety, and sandboxing

Approval policy is split across:

- command-approval policy
- network-approval policy
- sandbox mode

Built-in shell safety features:

- trusted read-only commands do not require approval in `unless-trusted` mode
- suspicious escalation tokens such as `sudo`, `su`, `doas`, `nsenter`, `LD_PRELOAD`, and shell metacharacters trigger approval or blocking logic
- session-scoped approval caching uses a stable command prefix key

Network safety:

- tools marked `requires_network_approval=True` go through per-target approval unless the domain is pre-approved
- `web_search` and `web_fetch` are the main users of this gate

Sandbox modes:

- `read-only`
- `workspace-write`
- `danger-full-access`

Platform-specific reality:

### Windows

- the Windows sandbox is not a full restricted-token sandbox today
- it performs path-grant checks in workspace-scoped modes
- it can attach spawned processes to a Job Object
- it currently returns the command largely unchanged instead of truly spawning under a restricted user token

This is the single biggest safety gap in the implementation.

### Linux

- uses `bwrap` if available
- `read-only` and `workspace-write` unshare the network
- workspace-write binds the cwd and writable roots back into the namespace

### macOS

- uses `/usr/bin/sandbox-exec` with generated Seatbelt profiles
- network is denied in read-only and workspace-write profiles

Dependency limits:

- Linux sandbox requires `bwrap`
- macOS sandbox requires `sandbox-exec`
- Windows restricted semantics are partial even when `pywin32` is installed

## Persistence, logs, and analytics

Bob persists a large amount of runtime state under `~/.bob`.

Important files/databases:

- `state.sqlite`: thread/session index and memory table
- `sessions/*.jsonl`: rollout files
- `analytics.db`: token/cost history
- `tasks.db`: simple task database used by `task_*` tools
- `schedules.db`: cron schedules
- `app_events.sqlite`: app-server realtime event bus
- `tasks_runtime.sqlite`: app-server task runtime state
- `logs/actions/*.log`: session action logs
- `logs/tui/*.log`: TUI logs

Session operations supported:

- reset to a fresh session
- resume from a rollout path
- resume by session ID
- fork from prior history into a new session ID
- list prior sessions from the state DB

Analytics tracked per turn:

- input tokens
- output tokens
- cached input tokens
- estimated USD cost from model catalog pricing
- latency
- changed files
- compaction counts and token reduction

## MCP, plugins, and skills

### MCP

Bob can connect to MCP servers over:

- stdio
- SSE
- HTTP

Discovery sources:

- explicit Bob config
- Bob-owned local plugin roots
- optionally imported Claude settings and Claude plugin directories

MCP behavior:

- tools are prefixed as `<server_name>__<tool_name>` internally before registration
- resources can be listed and read separately
- connected and failed server lists are emitted at startup

### Plugins

Plugin roots:

- `~/.bob/plugins`
- `<repo>/.bob/plugins`

Supported plugin manifests:

- `plugin.toml`
- `.claude-plugin/plugin.json`
- `.codex-plugin/plugin.json`

Capabilities:

- install from path
- install from URL
- install from remote registry
- uninstall
- list installed plugins
- discover MCP bundles and skill bundles shipped inside plugins

### Skills

Skill discovery sources:

- `~/.bob/skills`
- `<repo>/.bob/skills`
- plugin-injected skill metadata

Supported skill formats:

- Bob-native `skill.toml` plus `skill.md`
- `SKILL.md` with YAML frontmatter in Claude/Codex style

Invocation model:

- skills are not a separate runtime engine
- Bob injects skill content as a developer-message override turn

## Tasks and multi-agent support

There are two separate task concepts in this codebase.

### Simple local task DB

Used by model tools:

- `task_create`
- `task_update`
- `task_list`
- `task_get`
- `task_output`
- `task_stop`

Backed by:

- `bob/core/task_db.py`
- SQLite in `~/.bob/tasks.db`

### App-server runtime tasks

Used by JSON-RPC `tasks.*` and `exec.*` routes:

- queue-backed runtime
- worker loop
- typed executors like `local_shell` and `remote_shell`
- event-bus publication for task lifecycle updates

### Sub-agents

Core behavior:

- only available in non-ephemeral parent sessions
- child sessions are created as ephemeral
- child sessions force `ask_for_approval=never`
- child sessions auto-approve network access
- child sessions can inherit no history, all history, or a last-N slice

Important limitations:

- sub-agents cannot spawn deeper sub-agents; `AgentRegistry` is created with `max_depth=1`
- app server does not currently expose sub-agent methods

## Web research implementation

`web_search` is a multi-provider search tool.

Provider order can include:

- `ddg`
- `brave`
- `serpapi`
- `ddg_html`

Capabilities:

- single-query or multi-query search
- domain filtering
- fallback across providers
- optional page fetch of top results
- proxy support

Important limitations:

- Brave and SerpAPI need API keys
- fetched-page support depends on `httpx`
- DuckDuckGo provider depends on `ddgs` or compatible package availability
- provider results are summarized into plain markdown text, not normalized structured objects returned to the user

## What Bob can do well

As implemented today, Bob is strong at:

- repo reading, search, and targeted file edits
- shell-driven coding workflows
- model/tool iterative execution
- multi-provider model routing
- persistent session history
- cost and token tracking
- plugin, skill, and MCP-based extensibility
- JSON-RPC embedding for IDE or external clients
- authenticated browser assistance through the companion extension

## What Bob cannot do, or cannot do fully

This is the most important "limits" section.

### Not fully implemented or partial

- Windows sandboxing is partial, not a true locked-down restricted-token sandbox.
- `review.submit` in the app server is a stub. It only flags `TODO` markers and is not a real code-review engine.
- `exec --full-auto` does not currently implement true approval bypass behavior.
- the TUI slash-command dispatcher contains stale branches for commands that do not exist in the active enum.
- app-server capabilities claim no agent support even though core sessions support agents.

### Requires external dependencies or connected components

- browser control requires the Chrome extension to be connected
- Linux sandboxing requires `bwrap`
- MCP usefulness depends on configured servers actually connecting
- some search providers require API keys
- plugin registry access depends on network

### Intentionally constrained

- plan mode blocks mutating tools
- non-ephemeral features such as sub-agents are disabled in ephemeral sessions
- tool parallelism is conservative and excludes mutating tools
- screenshot-heavy browser usage is intentionally discouraged
- dynamic tools have registration and output-size limits

### Architectural tradeoffs

- context size is managed with heuristic token estimation, not provider-accurate tokenization for every item
- compaction is model-generated and can lose detail
- tool search uses simple scoring over descriptors, not a richer semantic retrieval layer

## Key implementation risks and maintenance notes

The codebase is substantial and functional, but a few risks stand out:

- There is visible drift between some advertised behavior and implementation detail.
- TUI command handling appears to have legacy code paths that were not fully removed.
- The app server is more mature for threads/turns/files/exec/tasks than for review or agent orchestration.
- Windows safety guarantees are weaker than the cross-platform abstractions suggest.

## Bottom line

Bob CLI is a real agent runtime, not a thin prompt wrapper. Its center of gravity is:

- `BobSession` for lifecycle
- `run_turn()` for iterative model execution
- `ToolOrchestrator` for tool policy and execution
- `ToolRegistry` for extensibility
- `LiteLLMClient` plus `BobClient` for provider routing
- the TUI and app server as two different shells around the same core session engine

If you want to reason about Bob quickly, the most important files to read first are:

1. `bob/cli/main.py`
2. `bob/core/session.py`
3. `bob/core/turn.py`
4. `bob/core/tool_orchestrator.py`
5. `bob/tui/interface.py`
6. `bob/llm/compatibility.py`
7. `bob/app_server/server.py`

