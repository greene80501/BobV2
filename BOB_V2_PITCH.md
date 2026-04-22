# Bob v2 — The AI-Powered Development Partner

> **Built by IBM. Designed for everyone.**
> Bob v2 is a terminal-native AI coding agent that gives developers the full power of the world's best LLMs — any provider, any model — with an enterprise-grade feature set that outclasses both Claude Code and OpenAI Codex CLI.

---

## Table of Contents

1. [What Is Bob v2?](#what-is-bob-v2)
2. [The Headline Advantages](#the-headline-advantages)
3. [Complete Feature List](#complete-feature-list)
4. [LLM Provider Coverage](#llm-provider-coverage)
5. [Tool Catalog (~60 Tools)](#tool-catalog)
6. [Slash Commands (60+)](#slash-commands)
7. [TUI / User Experience](#tui--user-experience)
8. [Multi-Agent System](#multi-agent-system)
9. [Safety, Approvals & Sandboxing](#safety-approvals--sandboxing)
10. [Context Management & Compaction](#context-management--compaction)
11. [Memory, Skills & Plugins](#memory-skills--plugins)
12. [Configuration System](#configuration-system)
13. [IDE Integration & App Server](#ide-integration--app-server)
14. [Analytics & Cost Tracking](#analytics--cost-tracking)
15. [Head-to-Head Comparison](#head-to-head-comparison)
16. [Why Bob Wins](#why-bob-wins)

---

## What Is Bob v2?

Bob v2 is a **hands-on AI coding agent embedded directly in the developer's terminal**. It reads and edits your files, runs shell commands, searches the web, manages multi-agent teams, and integrates with your IDE — all through a rich, interactive TUI or a headless CLI for automation pipelines.

- **Language:** Python 3.11+ — drop-in for any Python/IBM shop, zero exotic runtime dependencies
- **Package:** `pip install bob` — single command, running in seconds
- **Platforms:** Windows (PowerShell), macOS (zsh), Linux (bash) — full cross-platform parity
- **Default Model:** `gpt-5.1-codex-mini` via OpenAI Responses API
- **Supports:** 12+ LLM providers via LiteLLM + OpenAI Responses API dual-backend

---

## The Headline Advantages

### 1. Universal LLM Routing — No Vendor Lock-In
Claude Code works **only with Anthropic**. Codex works **only with OpenAI**. Bob works with **all of them** and 10 more providers simultaneously — switch models mid-session with a single `/model` command.

### 2. Feature Parity With Both Competitors — Then More
Every major feature Claude Code and Codex ship is in Bob: plan mode, MCP client + server, skills, memories, plugins, worktree isolation, multi-agent teams, cron scheduling, session rollout, IDE app server, review, commit, voice. Bob is not missing anything meaningful — and it adds features neither competitor has.

### 3. IBM-Built, Enterprise-Ready
Formal JSON-RPC 2.0 IDE protocol with auth + tracing middleware, schema export (`bob export-schemas`), audit-grade security logging, hooks for CI/CD integration, local-only analytics (no third-party telemetry by default), and a Python-native Windows sandbox (no native extensions required).

### 4. The Best LSP Integration in the Category
Five granular language-server tools (diagnostics, hover, definition, references, rename) built in as first-class citizens — more than Claude Code's single combined LSP tool, and entirely absent from Codex.

### 5. Computer-Use Without a Browser Extension
Bob ships a built-in computer-use tool (feature-flagged) — screenshot, click, type, scroll — with efficient JPEG-compressed screenshots. Codex has nothing equivalent. Claude Code pushes this to a Chrome extension.

---

## Complete Feature List

### Entry Points & CLI Surface

| Command | What It Does |
|---|---|
| `bob` | Launch the interactive TUI |
| `bob exec "PROMPT"` | Headless, scriptable single-turn execution |
| `bob app-server --stdio / --port 8765` | JSON-RPC 2.0 server for IDE extensions |
| `bob config set/get/unset/list KEY` | Dot-notation config editor |
| `bob mcp add/list` | MCP server management |
| `bob plugin list/install/uninstall/search` | Plugin lifecycle management |
| `bob completion bash/zsh` | Shell tab completion |
| `bob export-schemas` | Export protocol v1 JSON schemas for third-party clients |

**Headless flags:** `--last`, `--resume SESSION_ID`, `--json`, `--ephemeral`, `--full-auto`, `--yolo`, `-o/--output-last-message`

**TUI flags:** `-p/--prompt`, `-m/--model`, `-s/--sandbox`, `-a/--approval`, `--resume`, `-C/--cd`

---

## LLM Provider Coverage

Bob routes to 12+ providers — more than Claude Code and Codex **combined**:

| Provider | Models | Auth |
|---|---|---|
| **OpenAI (Responses API)** | `gpt-5*`, `o1/o3/o4-*`, `codex-*`, `gpt-5.1-codex-mini` | `OPENAI_API_KEY` |
| **OpenAI (Chat)** | `gpt-4o`, `gpt-4-*` | `OPENAI_API_KEY` |
| **Anthropic** | `claude-opus-*`, `claude-sonnet-*`, `claude-haiku-*` | `ANTHROPIC_API_KEY` |
| **Google Gemini** | `gemini-2.0-*`, `gemini-1.5-*` | `GEMINI_API_KEY` |
| **Google Vertex AI** | `vertex_ai/gemini-*` | GCP credentials |
| **Azure OpenAI** | Any deployment | `AZURE_API_KEY` + `AZURE_API_BASE` |
| **Kimi for Coding** | `kimi/kimi-for-coding` | `KIMI_API_KEY` |
| **OpenRouter** | 200+ models | `OPENROUTER_API_KEY` |
| **Groq** | Llama, Mixtral, etc. | `GROQ_API_KEY` |
| **Mistral** | All Mistral models | `MISTRAL_API_KEY` |
| **xAI (Grok)** | Grok-* | `XAI_API_KEY` |
| **Together AI** | 50+ open models | `TOGETHER_API_KEY` |
| **Ollama** | Any local model | None (localhost) |

**Smart routing:** Bob automatically normalizes tool names across providers (dots, colons, special chars), patches message history on retry, and routes dual-backend (Responses API vs Chat Completions) based on model prefix — transparently.

---

## Tool Catalog

Bob ships approximately **60 built-in tools**, each with a full JSON schema, parallel-safety flag, mutation flag, and keyword metadata for deferred discovery.

### File Operations
- `read_file`, `write_file`, `edit_file` — standard file I/O
- `apply_patch` — structured patch envelope for precise multi-file edits
- `list_dir`, `glob_files`, `grep_files` — filesystem navigation

### Shell & Execution
- `shell` — PowerShell (Windows), bash/zsh (Unix), cross-platform
- `js_repl` — embedded Node.js REPL for JavaScript evaluation

### Web
- `web_search` — DuckDuckGo by default; Brave/SerpAPI fallback
- `web_fetch` — BeautifulSoup-powered content extraction (not raw HTML)

### Language Server Protocol (5 tools — unique in this category)
- `lsp_diagnostics` — get compiler/linter errors for any file
- `lsp_hover` — type info and documentation at cursor
- `lsp_definition` — jump to definition
- `lsp_references` — find all usages
- `lsp_rename` — safe symbol rename across the project

### Multi-Agent
- `spawn_agent`, `assign_task`, `send_message`, `wait_agent`
- `list_agents`, `close_agent`, `resume_agent`

### Teams
- `team_create`, `team_spawn_agent`, `team_list`, `team_delete`

### Task System (persistent, async, SQLite-backed)
- `task_create`, `task_update`, `task_get`, `task_list`, `task_output`, `task_stop`

### Jupyter Notebooks
- `notebook_read`, `notebook_edit`

### Git Worktree Isolation
- `enter_worktree`, `exit_worktree`

### MCP Integration
- `mcp_list_resources`, `mcp_read_resource`, `mcp_authenticate` (OAuth 2.0 PKCE)

### IDE Bridge
- `ide_get_active_file`, `ide_get_open_files`, `ide_get_selection`, `ide_get_diagnostics`

### Planning & Mode
- `update_plan` — visible step-by-step checklist during task execution
- `todo_write` — persisted `.bob-todos.json`
- `enter_plan_mode` / `exit_plan_mode` — restricts write tools for safe planning

### Scheduling & Automation
- `schedule_cron` — recurring task scheduling with cron expressions
- `remote_trigger` — external trigger for scheduled task execution

### Computer Use (feature-flagged)
- `computer_use` — screenshot, left_click, right_click, double_click, mouse_move, scroll, key, type, cursor_position
- Efficient JPEG-q15 base64 encoding (~2–4K tokens per screenshot)
- Works on Windows (mss + pyautogui), macOS, Linux

### Utilities
- `view_image`, `request_user_input`, `tool_search`, `sleep`

---

## Slash Commands

60+ slash commands with fuzzy matching (rapidfuzz), prefix-preference bias, and mid-turn availability control.

### Model & Reasoning
`/model` · `/fast` · `/effort low|medium|high` · `/think [N tokens]`

### Session Management
`/new` · `/resume` · `/fork` · `/rename` · `/compact` · `/rewind [N]` · `/clear`

### Git & Code
`/diff` · `/review` · `/commit` · `/branch <name>` · `/init` (generates `AGENTS.md`)

### Context & Output
`/mention` · `/context <url|path>` · `/export` · `/summary`
`/output-style` · `/brief` · `/personality` · `/theme` · `/statusline` · `/title`

### Multi-Agent
`/agent` · `/subagents` · `/collab`

### Tools & Extensions
`/skills` · `/hooks` · `/mcp` · `/apps` · `/plugins`

### Info & Debug
`/status` · `/cost` · `/usage` · `/ps` · `/stop` · `/doctor`
`/debug-config` · `/rollout` · `/help`

### Safety & Approvals
`/approvals` · `/permissions` · `/setup-default-sandbox`
`/sandbox-add-read-dir <path>` · `/experimental`

### Planning & Tasks
`/plan` · `/tasks [status]`

### Input & Other
`/vi` · `/realtime` · `/settings` · `/feedback` · `/logout` · `/quit` · `/exit` · `/copy`

---

## TUI / User Experience

Bob's TUI is built on **prompt_toolkit** (3,733 lines) with full markdown rendering using CommonMark (`markdown-it` backend, legacy regex fallback).

### Welcome Experience
- ASCII logo banner
- Current model, workspace, and working directory info
- Last 3 git commits at a glance
- Quick commands panel

### Conversation Display
- Streaming text deltas with real-time rendering
- Reasoning/thinking blocks (collapsible)
- Tool call + results with `source: file:line` attribution
- Error messages with context

### Status Line (per-turn, configurable)
```
claude-sonnet-4-6 · 1,234 in 892 out · $0.0041 · 23% ctx · 3,201ms · 4 files changed
```

### Keybindings
| Key | Action |
|---|---|
| `Enter` | Submit message |
| `Tab` | Autocomplete slash commands and `@` file mentions |
| `Up/Down` | History navigation |
| `Ctrl+V` / Right-click | Paste text or clipboard image |
| `Ctrl+C` | Interrupt turn (twice to exit) |
| `Ctrl+R` | Reverse history search |
| `Escape` | Cancel autocomplete |
| `!cmd` | Passthrough shell command |

### Clipboard Image Paste (Cross-Platform)
- **Windows:** `Get-Clipboard -Format Image` → PNG temp file
- **macOS:** `osascript` clipboard access
- **Linux:** `xclip` or `wl-paste` (Wayland-aware)
- Auto-detects image file paths and inserts `@/path/to/image`

### Approval Prompt UI
Interactive `y` / `a` (approve all this session) / `n` / `d` (abort turn) with full command + cwd display — no guessing what Bob is about to run.

### Autocomplete
- Slash commands: fuzzy-matched with recency bias
- File mentions: `@` triggers glob of current working directory

---

## Multi-Agent System

Bob ships a production-grade multi-agent architecture with three layers:

### Thread Manager
Spawns, kills, lists, assigns tasks to, and resumes agent threads. Each agent gets its own tool context and conversation history.

### Collaboration Modes (5 Presets)

| Mode | Max Agents | Timeout | Tools | Purpose |
|---|---|---|---|---|
| `default` | 8 | 1800s | All (mutating) | General purpose |
| `planner` | 4 | 1200s | Read-only | Planning passes |
| `implementer` | 8 | 2400s | Write-enabled | Code generation |
| `reviewer` | 4 | 1200s | Read-only | Code review |
| `verifier` | 4 | 1200s | Read-only | Testing/verification |

### DAG-Based Agent Supervisor
`AgentSupervisor` executes `WorkflowNode(id, role, task, deps)` graphs. Ready nodes run in parallel (`asyncio.wait FIRST_COMPLETED`), dependency-blocked nodes wait automatically, failures propagate through the DAG. This is true parallel agentic workflow — not just sequential chaining.

### Team Abstraction
Named teams (`team_create`) with shared instructions automatically prepended to every spawned agent's context. Agents in a team inherit team goals without repetitive prompting.

### Policy Engine
- `max_agents = 8`, `max_depth = 5`, `max_runtime_seconds = 3600`
- Per-agent `allowed_cwds` and `allowed_tools` — granular containment
- Agent-level memory (`agent_memory.py`) for working state

---

## Safety, Approvals & Sandboxing

### Approval Modes
- `never` — always approve (full auto / yolo mode)
- `unless-trusted` — auto-approve safe read-only commands
- `on-request` — approve only when Bob explicitly asks
- `on-failure` — re-run with approval on non-zero exit

### Trusted Command Engine
A large hardcoded allowlist covering:
- **Unix read-only:** `ls`, `cat`, `grep`, `find`, `rg`, `fd`, `wc`, `head`, `tail`, `stat`, etc.
- **Windows read-only:** `dir`, `Get-ChildItem`, `Get-Content`, `Select-String`, etc.
- **Git read-only:** `git status`, `git log`, `git diff`, `git branch`, `git show`
- **Version checks:** `python --version`, `pip list`, `npm list`, etc.

### Escalation Detection
`_canonicalize_command()` unwraps shell wrappers (`cmd /c`, `powershell -Command`, `bash -c`) so commands can't bypass trust checks by wrapping dangerous operations.

`detect_escalation()` blocks:
- `sudo`, `su`, `doas`, `chroot`, `nsenter`, `unshare`, `pivot_root`
- `ptrace`, `strace`, `ltrace`
- `LD_PRELOAD=…`, `LD_LIBRARY_PATH=…`
- `setuid`, `setgid`, `setcap`
- Shell metachar injection (`|`, `;`, `&`, `` ` ``, `$`) in trusted-command arguments

**Security audit logger:** `bob.security.escalation` — all escalation attempts logged for audit.

### Sandboxing (True Cross-Platform Containment)

| Platform | Mechanism | Approach |
|---|---|---|
| **Windows** | `WindowsJobObject` via ctypes | `CreateJobObjectW` + `KILL_ON_JOB_CLOSE` + `ACTIVE_PROCESS_LIMIT=32` — zero native extensions |
| **macOS** | `sandbox-exec` | Generated Scheme policy, `file-write*` restricted to cwd |
| **Linux** | `bwrap` (bubblewrap) | `--ro-bind / /` + `--bind CWD CWD` |

**Sandbox modes:** `disabled`, `workspace-write`, `workspace-write-no-exec`

**Network controls:** `network_access` flag, `approved_network_domains` allowlist, `network_proxy` for enterprise routing.

**Granular approval overrides:** per-tool and per-domain trust rules configurable in `config.toml`.

---

## Context Management & Compaction

### Four-Tier Compaction Strategy (Unique)
No other tool in this category has four distinct triggers:

1. **Manual** — `/compact` command
2. **Auto** — fires when `auto_compact_threshold_tokens` is exceeded
3. **Reactive** — triggers inside `_stream_once` on context overflow error (handles unexpected overflow mid-call)
4. **Mid-turn** — fires during tool-heavy turns when approaching the limit

Each compaction asks the LLM to summarize the conversation preserving all technical details, then replaces full history with summary + most-recent N turns, and retries the original turn transparently.

**Compaction telemetry:** count, reason breakdown, bytes/tokens saved, success/failure counts — tracked in analytics SQLite.

### Budget Math
```
effective_limit = model_context_window × 0.85
compact_trigger = effective_limit − 8,000
reserve_output   = 12,000 tokens
```

### Context Operations
- `/rewind N` — precise "undo last N user turns" via boundary scan
- `trim_oldest_tool_results(keep_recent=40)` — preserves recent tool context
- `trim_oldest_assistant_messages(keep_recent=24)` — preserves recent responses
- Auto-compact threshold, reactive, and mid-turn modes all configurable independently

### Session Persistence (Rollout)
- SQLite at `~/.bob/rollouts/rollout.db`
- Stores: UUID session ID + title, cwd, model, full conversation JSON, timestamps, tool-call activity
- `bob exec --last` → resume most recent session
- `bob exec --resume SESSION_ID` → direct resume
- `/resume` → interactive session picker sorted by last-active
- `--ephemeral` flag to skip persistence for throwaway sessions

---

## Memory, Skills & Plugins

### Memory System
- Persistent per-project memories at `~/.bob/memories/`
- `raw_memories.md` (consolidated) + `rollout_summaries/*.md` (per-session)
- Each memory: Markdown with frontmatter (`name`, `description`, `type` ∈ {user, feedback, project, reference})
- Loaded at session start (up to 5,000 tokens cap)
- Debug commands: `/debug-m-drop`, `/debug-m-update`

### Skills System
- Skills are Markdown/TOML files in `~/.bob/skills/` (user) and `<cwd>/.bob/skills/` (repo)
- File watcher (`watchfiles`) auto-reloads skills without restart
- Activated via `/skills` — content appended to system prompt
- Supports `triggers` metadata for suggested activation
- Dual scope: user-global skills and repo-local skills

### Plugin System (3 Install Sources)
```bash
bob plugin install ./my-plugin/        # local path
bob plugin install https://example.com/plugin.zip   # URL zip
bob plugin install my-plugin-name      # remote registry
```
- Plugin manifest: `plugin.toml` (name, version, description, enabled)
- `bob plugin list/search/uninstall` — full lifecycle management
- Registry URL configurable — path to a Bob plugin marketplace

### Hooks System (7 Event Types)
```toml
[[hooks]]
event = "pre_tool_call"
command = "echo tool: $BOB_TOOL_NAME"
match_tool = "shell"
timeout_seconds = 5
blocking = false
```

| Event | Trigger |
|---|---|
| `session_start` | Before first turn |
| `session_end` | After session closes |
| `turn_start` | Before each turn |
| `turn_end` | After each turn |
| `pre_tool_call` | Before a tool executes |
| `post_tool_call` | After a tool executes |
| `user_message` | On any user input |

`blocking = true` → non-zero hook exit **prevents** the triggering action. Ideal for CI-style guardrails.

---

## Configuration System

Config is Pydantic v2 — validated, typed, documented.

**Load order (later wins):**
Pydantic defaults → `~/.bob/config.toml` → `./bob.toml` → `AGENTS.md` workspace overrides → CLI flags → environment variables

**File locations:** `%USERPROFILE%\.bob\config.toml` (Windows) · `~/.bob/config.toml` (macOS/Linux)

### Key Configuration Groups

**Identity & API**
- `model`, `api_key`, `base_url`
- `providers` — per-provider overrides (api_key, base_url, api_version, project, location, credentials_path, organization, headers, env, extra_kwargs)
- `prompt_caching` — enable Anthropic prompt caching

**Reasoning**
- `reasoning_effort` — LOW / MEDIUM / HIGH
- `reasoning_summary` — include reasoning in responses
- `thinking_budget_tokens` — token budget for extended thinking

**Approval & Safety**
- `ask_for_approval` — never / unless-trusted / on-request
- `granular_approval` — per-tool approval overrides
- `trusted_commands` — custom allowlist with glob/regex patterns

**Sandbox**
- `sandbox_mode` — disabled / workspace-write / workspace-write-no-exec
- `writable_roots`, `network_access`, `approved_network_domains`
- `windows_sandbox_level`, `network_proxy`

**Context & Compaction**
- `max_context_turns` (default 50)
- `auto_compact_threshold_tokens`, `max_context_tokens`
- `effective_context_window_percent` (0.85)
- `enable_reactive_compaction`, `enable_mid_turn_compaction`
- `compact_max_retries` (3)

**Collaboration**
- `collaboration_mode` — default / planner / implementer / reviewer / verifier

**MCP**
- `mcp_servers` — `{command, args, env}` per server
- `mcp_auth_tokens` — OAuth tokens

**UI**
- `theme`, `no_color`, `quiet`, `show_token_usage`, `show_cost`, `stream_responses`, `markdown_engine`

**Skills & Memories**
- `enable_skills`, `skill_paths`, `enable_memories`, `memories_path`

**Feature Flags**
- `enable_realtime`, `enable_review`, `enable_background_terminals`, `enable_guardian`
- `feature_flags = {computer_use = true}`

---

## IDE Integration & App Server

### JSON-RPC 2.0 App Server
Two transports: WebSocket (`bob app-server --port 8765`) or stdio (`bob app-server --stdio`).

**10 Route Modules:**

| Route | Capability |
|---|---|
| `agents` | Agent thread management |
| `config` | Read/write config remotely |
| `exec` | Non-interactive execution |
| `files` | File operations |
| `tasks` | Task CRUD |
| `threads` | Session/thread management |
| `turns` | Submit turns, stream events |
| `review` | Code review trigger |
| `realtime` | Voice/realtime mode |
| `dynamic_tools` | Register tools at runtime |

**Middleware stack:**
- `validation_middleware` — request schema validation
- `auth_middleware` — token-based auth
- `tracing_middleware` — distributed tracing

**Event bus:** persisted SQLite at `~/.bob/app_events.sqlite`

### Protocol v1 Schema Export
```bash
bob export-schemas
```
Emits Pydantic-generated JSON Schema for all protocol types — enabling IDE vendors and third-party clients to build against a stable, versioned spec. Neither Claude Code nor Codex ships an equivalent public schema export.

### MCP Server Mode
Bob can run **as** an MCP server, exposing its tools to other agents and workflows. Combined with its MCP client, Bob is both a consumer and provider in any MCP ecosystem.

### MCP OAuth 2.0 PKCE Flow
Full RFC 7636 implementation:
1. SHA256 verifier + base64url challenge
2. Browser opens to authorization URL
3. asyncio HTTP server on port 7890 catches redirect
4. Code exchange → token saved to `~/.bob/config.toml`

---

## Analytics & Cost Tracking

### Per-Turn Telemetry (SQLite at `~/.bob/analytics.db`)
Every turn records:
- Session ID, timestamp, model, provider
- Input / output / cached-input tokens (split separately)
- **Real cost** — input cost + output cost + cached input cost (at the discounted cached rate)
- Latency (ms)
- List of changed files

### Model Pricing Catalog (`llm_database.db`)
An independent, maintainable SQLite database with:
- Per-1M-token input and output rates for every model
- Separate cached-input rate (falls back to `input_rate × 0.1` if unspecified)
- `ModelCatalog` reads this at startup — keeps pricing current without code changes

### Status Line Cost Display
```
gpt-5.1-codex-mini · 2,341 in / 891 out (cached: 1,200) · $0.0023 · 31% ctx · 2,847ms
```

### Session & Compaction Metrics
- `session_input_tokens`, `session_output_tokens`, `session_cost_usd`, `session_turns`
- Compaction: count, reason breakdown, tokens saved, success/failure

### File Change Detection Per Turn
Before/after snapshot of cwd (capped at 5,000 files, skips `__pycache__`, `.git`, `node_modules`, `.venv`). Reports "N files changed" in the status line — real work visibility.

### Commands
- `/cost` — current session cost breakdown
- `/usage` — token usage summary
- Status line — live per-turn stats

---

## Head-to-Head Comparison

| Capability | Bob v2 | Claude Code | Codex CLI |
|---|---|---|---|
| **Language / Runtime** | Python 3.11+ | TypeScript on Bun | Rust |
| **UI** | prompt_toolkit + rich | React + Ink | Ratatui |
| **LLM Providers** | **12+ (all major)** | Anthropic only | OpenAI + Ollama |
| **Default Model** | gpt-5.1-codex-mini | Claude family | OpenAI/ChatGPT |
| **Tool Count** | ~60 | ~40 | Comparable |
| **Slash Commands** | 60+ | ~85 | ~45 |
| **LSP Tools** | **5 granular** | 1 combined | None exposed |
| **Computer Use** | **Built-in (feature-flagged)** | Chrome extension only | Not available |
| **MCP Client** | Yes + OAuth PKCE | Yes | Yes |
| **MCP Server** | Yes | Yes | Yes |
| **Sandbox** | Job Object / sandbox-exec / bwrap | Light toggle | Deepest (Landlock + Seatbelt + ACL) |
| **Skills** | Yes (user + repo scope) | Yes (16 bundled) | Yes |
| **Memories** | Yes | Yes + auto-extraction | Yes |
| **Plugins** | **3 install sources** | Marketplace + builtins | Present but lighter |
| **Hooks** | **7 events, blocking mode** | Yes | Yes |
| **Plan Mode** | Yes | Yes | Yes |
| **Worktree Isolation** | Yes | Yes | Yes |
| **Cron / Scheduled Tasks** | Yes | Yes | Yes |
| **Cloud / Remote Tasks** | No | `/teleport`, `/desktop`, `/mobile` | `cloud-tasks/` crate |
| **Voice / Realtime** | Experimental | Full (VOICE_MODE) | Realtime crate |
| **IDE Protocol** | **JSON-RPC 2.0 + middleware + schema export** | Bridge (internal JWT) | App-server crate |
| **Protocol Schema Export** | **`bob export-schemas`** | None public | `config.schema.json` only |
| **Multi-Agent Modes** | **5 (default/planner/implementer/reviewer/verifier)** | Coordinator mode | Agent registry |
| **DAG Agent Supervisor** | **Yes** | `coordinator/` (gated) | Less prominent |
| **Team Abstraction** | **team_create / team_spawn_agent** | TeamCreate/Delete | Lighter |
| **Real Cost Tracking** | **Cached-rate split + catalog DB** | Via `/cost` | Via analytics crate |
| **File Change Detection** | **Per-turn snapshot diff** | Not shown per-turn | Not shown per-turn |
| **Compaction Triggers** | **4 (manual/auto/reactive/mid-turn)** | Compaction service | compact + compact_remote |
| **Windows UTF-8 Fix** | **Auto re-exec `-X utf8`** | Not needed (Bun) | Not present |
| **Cross-Platform Clipboard Image** | **Win/macOS/Linux** | Yes | Yes |
| **Approval Escalation Guard** | **Unwrap + LD_PRELOAD block + audit log** | Permission rules + ML auto-mode | execpolicy + shell-escalation crates |
| **Enterprise Telemetry** | **Local SQLite only (no 3rd party)** | GrowthBook + OTel + gRPC | OpenTelemetry |
| **Open Source** | IBM internal | Leaked (Anthropic-owned) | Apache-2.0 |

---

## Why Bob Wins

### For Enterprises
- **No vendor lock-in.** Switch from OpenAI to Anthropic to Gemini to local Ollama without changing a line of configuration — just update `model` in `config.toml`.
- **Local analytics only.** No GrowthBook, no gRPC telemetry callbacks, no A/B test enrollment. Your code stays in your environment.
- **Hooks as a compliance layer.** `blocking = true` hooks can enforce policy — reject shell commands, log tool calls, gate on external approval — without modifying Bob's source.
- **Formal protocol schema.** `bob export-schemas` ships versioned JSON schemas enabling IDE integrations, internal tooling, and audit systems to stay in sync with the protocol spec.
- **Python.** Auditable, extensible, embeddable in existing IBM/enterprise Python infrastructure without Bun or Rust prerequisites.

### For Developers
- **One tool, every model.** Test the same prompt against GPT-5, Claude Sonnet, Gemini 2.0, and Kimi for Coding in the same session with `/model`.
- **LSP that actually works.** Five granular language-server tools mean Bob can get diagnostics, hover docs, jump to definition, find references, and rename symbols — using your existing language server, for any language.
- **Real cost visibility.** The status line shows exact cost per turn, with cached-token pricing split out. You always know what you're spending.
- **Computer use when you need it.** Screenshot the UI, click a button, fill a form — without leaving the terminal or installing a browser extension.
- **Windows is a first-class citizen.** UTF-8 self-reexec, PowerShell-aware trusted commands, clipboard image paste, Windows Job Object sandboxing — Windows works as well as macOS or Linux.

### For Platform Teams
- **Plugin marketplace path.** Three install sources (local path, URL zip, remote registry) with a configurable registry URL means you can run an internal Bob plugin marketplace today.
- **App server as a platform.** The JSON-RPC 2.0 server with auth/tracing middleware is designed to be embedded in IDE extensions, internal dashboards, and CI pipelines — not just used from the terminal.
- **DAG multi-agent for complex workflows.** The `AgentSupervisor` with 5 collaboration modes and runtime policies enables structured, parallelized agentic pipelines: plan → implement → review → verify, all orchestrated automatically.
- **MCP as both client and server.** Bob consumes MCP tools from external servers and exposes its own tools to other MCP clients — making it a first-class node in any MCP ecosystem.

---

## Summary

Bob v2 is what you get when you take **Codex's best-in-class CLI architecture**, **Claude Code's feature breadth**, add **universal LLM routing across 12+ providers**, build it in **Python for enterprise embeddability**, and stamp it with **IBM quality** for internal and external deployment.

It is the only AI coding agent in this category that:
- Works with every major LLM provider simultaneously
- Ships 5 granular LSP tools as first-class capabilities
- Includes computer-use without a browser extension
- Exports a formal JSON-RPC protocol schema for third-party integrators
- Uses four distinct compaction strategies with per-turn telemetry
- Tracks real per-turn cost with cached-token rate splitting
- Runs a complete plugin/skills/memory/hooks stack on every platform
- Treats Windows as a first-class platform, not an afterthought

**Bob v2: Your AI development partner. Any model. Any platform. Enterprise-ready.**

---

*Document generated from source analysis of `bobV2/`, `claude-code/`, and `codex/` directories.*
*Bob v2 version: 0.1.0 · Python 3.11+ · Default model: gpt-5.1-codex-mini*
