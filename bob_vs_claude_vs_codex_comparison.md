# BobV2 vs Claude Code vs Codex

Last updated: 2026-04-10

Scope: this comparison is based on the local repositories in:

- `C:\Users\green\bob_v2_new_code_geb\bobV2`
- `C:\Users\green\bob_v2_new_code_geb\claude-code`
- `C:\Users\green\bob_v2_new_code_geb\codex`

The goal here is not marketing. It is an implementation-level read of what Bob actually has, what is partial, and what Claude Code and Codex already do that Bob does not.

## Executive Summary

BobV2 is a real agentic coding assistant, not just a thin shell wrapper. It has:

- a working session and turn engine
- approval-aware shell execution
- file/search/edit tools
- in-process multi-agent support with sub-agent templates and memory snapshots
- session persistence, rollouts, analytics, and basic task tracking
- a strong model-routing story through OpenAI Responses plus LiteLLM-backed multi-provider support

But Bob is still much earlier-stage than both Claude Code and Codex.

The biggest difference is not just feature count. It is integration maturity:

- Claude Code and Codex have deeply integrated subsystems for skills, plugins, MCP, IDE/app-server surfaces, tasks, approvals, memories, and richer multi-agent orchestration.
- Bob has several of those pieces present as modules or configs, but some are only partially implemented, placeholder-level, or not wired into `BobSession` as first-class runtime systems.

If I reduce this to one sentence:

- Bob has a good small-core agent engine and unusually broad model/provider flexibility.
- Claude Code has the broadest end-user feature surface.
- Codex has the strongest systems architecture and the most complete platform/runtime substrate.

## Size And Stack

### BobV2

- Language/runtime: Python 3.11+, Textual, Typer
- Local size observed: about 118 tracked files, about 16k lines in the main explored set
- Core style: compact, hackable, single-package architecture

### Claude Code

- Language/runtime: TypeScript, Bun, React + Ink
- README states: about 1,900 files and 512k+ lines
- Core style: product-scale TypeScript app with many user-facing systems

### Codex

- Language/runtime: Rust monorepo with CLI, TUI, app-server, protocol, SDK, tools, sandbox crates
- Local size observed in explored set: about 3,329 files and about 661k lines
- Core style: platform-scale native system with reusable protocol/runtime layers

## BobV2 Deep Dive

## What Bob clearly has

### 1. Real agent/session runtime

Bob's core is centered around:

- `bob/core/session.py`
- `bob/core/turn.py`
- `bob/core/context_manager.py`
- `bob/rollout/recorder.py`
- `bob/core/task_db.py`

This is a real async session engine, not a toy REPL:

- queued ops and event streaming
- turn lifecycle events
- tool-call loop with iterative model/tool execution
- history/context management
- compaction support
- rollout persistence
- state DB/session index
- token/cost analytics hooks

### 2. Real built-in tool surface

Bob registers 43 built-in tools in `bob/core/session.py`:

- `shell`
- `update_plan`
- `view_image`
- `list_dir`
- `read_file`
- `write_file`
- `edit_file`
- `glob_files`
- `grep_files`
- `sleep`
- `todo_write`
- `enter_plan_mode`
- `exit_plan_mode`
- `web_search`
- `web_fetch`
- `schedule_cron`
- `remote_trigger`
- `js_repl`
- `notebook_read`
- `notebook_edit`
- `spawn_agent`
- `send_message`
- `wait_agent`
- `list_agents`
- `close_agent`
- `task_create`
- `task_update`
- `task_list`
- `task_get`
- `task_output`
- `task_stop`
- `request_user_input`
- `enter_worktree`
- `exit_worktree`
- `lsp_diagnostics`
- `lsp_hover`
- `lsp_definition`
- `lsp_references`
- `lsp_rename`
- `ide_get_open_files`
- `ide_get_selection`
- `ide_get_diagnostics`
- `ide_get_active_file`

That is a meaningful baseline. Bob is already beyond "shell + file edit only".

### 3. Good shell safety core

Bob has real execution-policy logic in:

- `bob/core/turn.py`
- `bob/core/exec_policy.py`
- `bob/core/network_policy.py`
- `bob/sandbox/*`

Implemented behaviors include:

- approval policies
- safe/trusted command handling
- command canonicalization
- escalation detection
- network approval flow for web tools
- sandbox runner abstraction by OS
- special `apply_patch` routing

This is one of Bob's stronger areas.

### 4. Real in-process multi-agent support

Bob's sub-agent system is not fake. It is implemented in:

- `bob/core/thread_manager.py`
- `bob/tools/multi_agent/*`
- `bob/core/agent_templates.py`
- `bob/core/agent_memory.py`

What it does:

- spawns full child `BobSession`s in the same event loop
- supports `spawn_agent`, `send_message`, `wait_agent`, `list_agents`, `close_agent`
- supports sub-agent templates: `explore`, `plan`, `verify`, `write`, `review`
- can persist named-agent memory snapshots and inject them into future runs
- forwards sub-agent output back to the parent session

For Bob's size, this is an impressive capability and one of the main reasons it is worth taking seriously.

### 5. Strong provider/model flexibility

This is Bob's clearest differentiator.

The model routing and provider compatibility layer in:

- `bob/llm/client.py`
- `bob/llm/compatibility.py`
- `bob/client/openai_client.py`

supports:

- native OpenAI Responses routing where needed
- LiteLLM fallback for other providers
- broad provider configuration via `[providers.*]`

The repo explicitly supports or maps for:

- OpenAI
- Anthropic
- Gemini
- Vertex AI
- Azure OpenAI
- OpenRouter
- Groq
- Mistral
- Cohere
- Together AI
- xAI
- Ollama
- catalog-backed unknown providers

Neither local Claude Code nor local Codex matches Bob's breadth here in such a direct built-in way.

### 6. Persistence and resumability

Bob has real persistence plumbing:

- rollout JSONL recorder
- state SQLite DB
- session index
- resume/fork support
- session naming
- context compaction

So Bob is not stateless.

## What Bob has only partially

These are important because they look stronger at the file-tree level than they are at runtime.

### 1. LSP support is placeholder-level

The `bob/tools/lsp_tools.py` file is mostly a scaffold:

- language server startup skeleton exists
- handlers return placeholder messages
- comments explicitly say full async LSP protocol handling is not implemented

Conclusion: Bob does not currently have production-grade semantic code navigation.

### 2. IDE bridge tools are stubs

`bob/tools/ide_bridge.py` defines:

- `ide_get_open_files`
- `ide_get_selection`
- `ide_get_diagnostics`
- `ide_get_active_file`

But the handlers mostly return "not yet implemented" or "IDE bridge not available" style fallback text.

Conclusion: Bob does not currently have a real integrated IDE bridge comparable to Claude/Codex.

### 3. App-server is minimal

`bob/app_server/server.py` is a very small JSON-RPC server.

Exposed methods are basically:

- `ping`
- `bob.session.create`
- `bob.session.submit`
- `bob.session.interrupt`
- `bob.session.shutdown`
- `bob.config.get`
- `bob.models.list`

That is nowhere near the rich thread/turn/fs/command/review/config/app/plugin/MCP surfaces in Codex app-server.

### 4. Task system is database-backed bookkeeping, not a full background worker system

Bob has:

- `task_create`
- `task_update`
- `task_list`
- `task_get`
- `task_output`
- `task_stop`

But the implementation is mostly CRUD against SQLite in `bob/core/task_db.py`.

It does not give Bob the kind of actual background shell/agent/remote task runtime that Claude Code has.

### 5. Cron scheduling is metadata-focused

`bob/tools/cron_tools.py` stores schedules and manual trigger records.

It does not appear to ship with a real scheduler daemon or remote execution fabric.

### 6. Worktree support is simpler than the others

Bob's `enter_worktree` / `exit_worktree` tools do real `git worktree` operations, but they are simple direct wrappers, not a broader isolated-workspace execution model.

## What Bob has on disk but does not appear to be fully integrated

This is the most important implementation-level finding.

### 1. MCP client infrastructure exists, but is not clearly wired into `BobSession`

There is a real MCP layer:

- `bob/mcp/client.py`
- `bob/mcp/manager.py`

But I did not find `McpManager` integrated into `BobSession.start()` or the turn runtime as a first-class subsystem.

That means Bob has MCP code, but not the same level of active runtime MCP support that Claude Code and Codex expose.

### 2. Skills system exists, but is not clearly part of the main session runtime

There is a real skills module:

- `bob/skills/manager.py`
- `bob/skills/watcher.py`

But I did not find `SkillsManager` wired into `BobSession` startup or turn-time injection.

### 3. Plugin system exists, but is not clearly integrated

There is a plugin manager:

- `bob/plugins/manager.py`

But I did not find it wired into the main Bob runtime in the same way Codex and Claude integrate plugins into startup, skills, MCP, and app surfaces.

### 4. Memory pipeline exists, but does not appear to run as a first-class startup subsystem

There are memories modules:

- `bob/memories/phase1.py`
- `bob/memories/phase2.py`
- `bob/memories/storage.py`

But they do not appear to be wired into `BobSession.start()` the way Codex's memory pipeline is explicitly designed.

### 5. MCP server exists, but is tiny and not exposed as a main CLI mode

`bob/mcp/server.py` only exposes:

- `shell`
- `view_image`
- `update_plan`

That is a far smaller MCP-server surface than the others, and there is no obvious polished top-level CLI path for it in `bob/cli/main.py`.

## Slash command maturity

Bob defines 60 slash commands in `bob/tui/slash_commands.py`, which is ambitious.

But `bob/tui/interface.py` also has a catch-all fallback:

- `/{cmd.value} not yet implemented`

So Bob's slash-command surface is broader than its fully implemented UI handling.

Conclusion:

- Bob's core engine is more mature than its UX surface.
- Some command names are ahead of their actual implementation.

## Bottom line on Bob

Bob today is best described as:

- a strong small-core Python coding agent
- with real tool use, approvals, persistence, and sub-agents
- with unusually broad model/provider support
- but still missing integrated maturity in skills/plugins/MCP/IDE/app-server/LSP/background systems

## Claude Code Deep Dive

## Core character

Claude Code is the broadest user-product codebase of the three.

Its local repo documents and contains:

- about 40 agent tools
- about 85 slash commands
- a React + Ink TUI
- an IDE bridge
- MCP client and server support
- plugins
- skills
- tasks
- memory system
- coordinator/team multi-agent mode
- voice
- remote/session handoff features
- server/web surfaces

Main architectural anchors:

- `claude-code/src/QueryEngine.ts`
- `claude-code/src/Tool.ts`
- `claude-code/src/tools.ts`
- `claude-code/src/commands.ts`
- `claude-code/src/bridge/`
- `claude-code/src/coordinator/`
- `claude-code/src/tasks/`
- `claude-code/src/plugins/`
- `claude-code/src/skills/`

## Areas where Claude Code is clearly ahead of Bob

### 1. Broader integrated tool surface

Claude's documented tool catalog includes:

- file I/O
- glob/grep
- shell and PowerShell
- REPL
- sub-agents
- teams
- planning mode
- worktree isolation
- MCP tools/resources/auth/tool-search
- LSP
- skills
- cron/remote triggers
- structured output tools

Bob overlaps with many names, but Claude's versions are part of a much more integrated product system.

### 2. Much broader command surface

Claude exposes a much richer slash-command layer than Bob, including:

- git flows
- review/security/advisor/bughunter
- session/share/export/context tooling
- plugin and MCP management
- privacy/auth/rate-limit flows
- IDE/desktop/mobile/teleport flows
- remote environment and setup
- diagnostics and analytics
- many internal/productized commands Bob simply does not have

### 3. Better task and agent orchestration

Claude has explicit task classes such as:

- `LocalShellTask`
- `LocalAgentTask`
- `RemoteAgentTask`
- `InProcessTeammateTask`
- `DreamTask`

This is a much more developed background-work model than Bob's SQLite task ledger.

### 4. Better integrated plugin + skill + memory + team systems

Claude has:

- plugin loader and marketplace concepts
- bundled and user skills
- persistent memory around `CLAUDE.md`
- extracted memories
- team memory sync

Bob has partial analogs on disk, but not this integration level.

### 5. Better IDE/product integration

Claude has a true bridge subsystem for VS Code / JetBrains plus desktop/mobile handoff concepts. Bob does not.

### 6. Better remote/cloud support

Claude includes remote agent/task concepts and remote session features that Bob currently lacks.

## Where Bob is stronger than Claude Code

### 1. Provider breadth

Bob's LiteLLM-driven multi-provider support is broader and cleaner than Claude's primary Anthropic-centered architecture.

Claude does support first-party and some 3P platform paths such as:

- Anthropic
- Bedrock
- Vertex AI
- Foundry

But Bob is stronger if the goal is "one local CLI that can target lots of model vendors quickly".

### 2. Simplicity and modifiability

Bob is much smaller and easier to reason about or rewrite.

Claude is more complete, but also far heavier.

## Codex Deep Dive

## Core character

Codex is the strongest systems/platform architecture in this repo set.

It is not just a CLI. It is a full stack made of:

- native Rust CLI/TUI
- `codex app-server`
- protocol and schema generation
- MCP client and MCP server
- plugin system
- skills system
- app/connectors layer
- collaboration/multi-agent layers
- multi-OS sandbox implementations
- local OSS model support
- reusable SDK/runtime components

Important directories:

- `codex-rs/core/src/`
- `codex-rs/app-server/`
- `codex-rs/app-server-protocol/`
- `codex-rs/tui/src/`
- `codex-rs/tools/`
- `codex-rs/plugin/`
- `codex-rs/core-skills/`
- `codex-rs/windows-sandbox-rs/`
- `codex-rs/ollama/`
- `codex-rs/lmstudio/`

## Areas where Codex is clearly ahead of Bob

### 1. Deep runtime architecture

Codex has first-class abstractions for:

- threads
- turns
- items
- app-server protocol
- typed JSON-RPC surfaces
- reusable protocol schemas
- in-process and remote clients

Bob has a decent session engine, but Codex is on another level architecturally.

### 2. Much richer app-server surface

`codex-rs/app-server/README.md` documents a huge API surface including:

- thread lifecycle
- turn lifecycle
- review
- realtime
- shell command execution
- fs read/write/copy/remove/watch
- command exec/resize/terminate
- model listing
- collaboration mode listing
- skills listing/config
- plugin list/read/install/uninstall
- app listing
- MCP OAuth and status
- config read/write/batch write
- external agent config import
- Windows sandbox setup

Bob's app-server is minimal by comparison.

### 3. Stronger multi-agent/collaboration infrastructure

Codex has:

- `/agent` and `/subagents`
- `AgentControl`
- `ThreadManager`
- collaboration modes
- protocol events for spawn/send/wait/close
- collaboration tool spec builders in `codex-rs/tools/README.md`

Bob's sub-agent runtime is good, but Codex has deeper protocol-level collaboration support.

### 4. Better integrated skills and plugins

Codex has:

- a dedicated `core-skills` crate
- skill dependency resolution and user-input prompting
- file watching for skill changes
- plugin bundles that can contribute skills, MCP servers, and apps
- curated plugin marketplace sync

This is substantially beyond Bob's current plugin/skill state.

### 5. Better integrated MCP

Codex has:

- MCP client config in core/config
- MCP server launcher support
- MCP OAuth flows
- resource and resource-template support
- app-server endpoints for server status and reload
- MCP server mode from the CLI

Bob has MCP code, but it is not integrated to this degree.

### 6. Better memory pipeline

Codex has a documented two-phase startup memory pipeline:

- rollout extraction
- global consolidation
- state DB coordination
- asynchronous background processing
- sub-agent consolidation run

Bob has memory modules, but not comparable integration.

### 7. Much stronger sandbox/platform layer

Codex has substantial OS-specific sandboxing infrastructure for:

- macOS
- Linux
- Windows

including dedicated crates for Windows sandbox setup and Linux sandbox support.

Bob has sandbox abstractions, but not this depth.

### 8. Better local model story than most OpenAI-centric tools

Codex still centers on OpenAI/ChatGPT auth, but it also has:

- built-in local OSS provider support via Ollama
- LM Studio support
- configurable model providers

So while Bob wins on broad vendor count, Codex already has a serious local-model path.

## Where Bob is stronger than Codex

### 1. Multi-provider breadth

Bob still wins if the metric is "how many upstream model vendors can I point this CLI at out of the box via one compatibility layer".

Codex is more opinionated:

- OpenAI / ChatGPT centered
- configurable providers
- local OSS providers like Ollama / LM Studio

That is good, but it is not Bob's LiteLLM-style breadth.

### 2. Lower complexity

Bob is easier to modify quickly if you want to experiment without carrying a huge Rust monorepo.

## Direct Comparison Matrix

Legend:

- Strong = mature and clearly integrated
- Partial = exists but limited or not fully integrated
- Weak = very thin implementation

| Area | BobV2 | Claude Code | Codex |
|---|---|---|---|
| Core agent loop | Strong | Strong | Strong |
| File/search/edit basics | Strong | Strong | Strong |
| Shell approvals/safety | Strong | Strong | Strong |
| Session persistence/resume | Strong | Strong | Strong |
| Multi-agent basics | Strong | Strong | Strong |
| Multi-agent depth | Partial | Strong | Strong |
| Team/remote agents | Weak | Strong | Strong |
| Task runtime | Partial | Strong | Strong |
| Worktree support | Partial | Strong | Strong |
| Plan mode | Strong | Strong | Strong |
| Web search/fetch | Strong | Strong | Strong |
| LSP/semantic navigation | Weak | Strong | Strong |
| IDE bridge | Weak | Strong | Strong |
| App-server/API surface | Weak | Strong | Strong |
| MCP client integration | Partial-to-Weak | Strong | Strong |
| MCP server mode | Weak | Strong | Strong |
| Skills integration | Partial-to-Weak | Strong | Strong |
| Plugins integration | Partial-to-Weak | Strong | Strong |
| Apps/connectors | Weak | Partial | Strong |
| Memory system | Partial | Strong | Strong |
| Realtime/voice | Weak | Strong | Strong |
| Remote/cloud execution | Weak | Strong | Strong |
| Multi-provider model breadth | Strong | Partial | Partial |
| Local OSS model support | Partial | Partial | Strong |
| Runtime/platform maturity | Partial | Strong | Strong |

## What Bob Already Has And Should Keep Leaning Into

These are Bob's real strengths.

### 1. Small-core architecture

Bob is still understandable end-to-end by one engineer.

### 2. Real sub-agents

Bob's in-process child-session approach is real and useful.

### 3. Good shell/approval foundation

This part is stronger than many early agent repos.

### 4. Excellent provider flexibility

This is Bob's cleanest differentiator today.

### 5. Reasonable persistence foundation

Rollouts, session DB, context compaction, and analytics are real assets.

## What Bob Does Not Have Yet, In Practice

If the question is "what are we missing versus Claude Code and Codex?", this is the shortest honest answer.

### Missing or underpowered versus both

- fully integrated MCP runtime
- fully integrated skills runtime
- fully integrated plugin runtime
- real app-server/IDE protocol surface
- real semantic LSP functionality
- richer background task runtime
- stronger memory pipeline integration
- richer remote/cloud execution features
- stronger realtime/voice features
- broader slash-command completion of implemented behavior

### Missing more specifically versus Claude Code

- broad end-user command surface
- remote agent/task fabric
- richer IDE/bridge workflows
- more complete plugin and memory/team systems
- more productized review/advisor/security flows

### Missing more specifically versus Codex

- typed app-server and protocol stack
- deep OS sandbox/runtime platform
- first-class plugins/apps/connectors integration
- first-class MCP OAuth/status/reload flows
- stronger collaboration protocol model
- stronger local-model operational path

## Practical Conclusion

If you compare all three as coding agents:

- Bob is already credible as a compact Python coding agent with solid fundamentals and great model-provider flexibility.
- Claude Code is much more complete as a product surface for interactive agent work.
- Codex is the most complete as a long-term architecture and systems platform.

If you compare them as codebases to evolve:

- Bob is easiest to move quickly in.
- Claude Code gives the biggest feature reference set.
- Codex gives the best architecture reference set.

If the goal is to make Bob competitive, the highest-value next upgrades are:

1. wire `SkillsManager`, `PluginsManager`, and `McpManager` directly into `BobSession`
2. replace placeholder LSP and IDE bridge implementations with real ones
3. expand app-server from minimal JSON-RPC into real thread/turn/tool/fs APIs
4. turn tasks/cron from metadata storage into actual worker execution infrastructure
5. make slash-command implementation match slash-command surface
6. promote memories from standalone modules into startup/runtime behavior

## Short Verdict

Bob is not feature-empty. It already has a real engine.

But compared to Claude Code and Codex, Bob is currently:

- closer to a strong early-stage core than a full platform
- ahead on model routing flexibility
- behind on integration depth, runtime breadth, and subsystem maturity
