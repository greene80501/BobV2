# Bob V2 Update Roadmap — Feature Gap Analysis
**vs Claude Code and Codex**  
_Last updated: 2026-04-06_

---

## How to Read This Document

Each item is tagged:
- `[CC]` = Claude Code has it  
- `[CX]` = Codex has it  
- `[CC+CX]` = Both have it  
- `PARTIAL` = Bob has a stub/incomplete version  
- `MISSING` = Bob has nothing for this yet  

Items are ordered by impact: high-value, user-visible wins first.

---

## 1. Terminal UI & Prompt Experience

### 1.1 Color — Status & Cost Display in Prompt Area `[CC+CX]` MISSING
Claude Code and Codex both display live metadata near the prompt:
- **Tokens used** (input + output count)
- **Context window % consumed** (e.g. `47% context used`)
- **API cost** (e.g. `$0.023`)
- **Model name** shown at prompt or in a status bar
- **Rate limit fill bar** (visual bar showing remaining quota)

Bob shows none of this. All the data is available from `TurnEndedEvent` (input_tokens, output_tokens) and `CostEstimateEvent` but nothing is rendered.

**Fix**: Display a dim status line after each turn completes:
```
  claude-sonnet-4-5  ·  1,234 in  456 out  ·  $0.018  ·  12% ctx
```

### 1.2 Streaming Diff Output `[CC+CX]` MISSING
When `apply_patch` runs, both Claude Code and Codex render a **colored unified diff** showing exactly what changed:
```
  ● Patch(src/main.py)
  ⎿  - old line
     + new line
```
Lines are colored: green for additions, red for deletions, matching standard diff conventions.

Bob currently shows only the filename — no diff preview at all.

**Fix**: In `ExecCompletedEvent` / `PatchApprovalRequestedEvent`, parse and render the patch using Rich's `Syntax` or custom ANSI diff coloring. Colors: `\033[32m` for `+` lines, `\033[31m` for `-` lines.

### 1.3 Vi / Vim Input Mode `[CC]` MISSING
Claude Code has a full vi-mode for the prompt input via `/vim` command.
- Normal/insert/visual modes  
- Standard motions: `h j k l w b e 0 $ ^ G gg`  
- Editing: `d w c i a x` etc.

Bob uses `prompt_toolkit` which has built-in vi mode support. Just needs to be wired up.

**Fix**: Add `vi_mode=True` to `PromptSession` (behind a config toggle or `/vim` slash command). Add `SlashCommand.VIM` to dispatch.

### 1.4 Multi-line Input with Shift+Enter `[CC+CX]` MISSING
Claude Code and Codex support multi-line prompt input — `Shift+Enter` inserts a newline, `Enter` submits.

Bob's `prompt_toolkit` PromptSession accepts only single-line input currently.

**Fix**: Pass a `multiline=True` key binding override to `PromptSession` where `Enter` (not `Meta+Enter`) submits, and `Shift+Enter` inserts newline. prompt_toolkit supports this via a custom `KeyBindings` object.

### 1.5 Theme Selection `[CC]` MISSING
Claude Code supports: `dark`, `light`, `dark-daltonized`, `light-daltonized`, `dark-ansi`, `light-ansi`. Selected via `/theme` command and persisted to config.

Bob currently hard-codes dark-terminal ANSI colors. The `no_color` config field exists but nothing adapts the UI.

**Fix**: Add `SlashCommand.THEME` dispatch. At minimum: `dark` (current), `light` (invert dim/bright), `no-color` (plain ASCII). Store in config. The `BRAND`, `DIM`, `BOLD` etc. variables in `_print_header` already make this easy to parameterize.

### 1.6 Status Line Hooks `[CC]` MISSING
Claude Code allows custom status line content via shell hooks — a command that runs and its stdout appears in the bottom status area. Bob has a hooks system (`bob/hooks/runner.py`) but it's not surfaced in the UI.

### 1.7 Image / Screenshot Input `[CC+CX]` PARTIAL
Bob has `bob/tools/view_image.py` but there's no mechanism in the TUI to attach an image from the prompt (e.g. paste path, drag-and-drop, or clipboard paste).

Claude Code supports `@image` attachments inline in the prompt.

---

## 2. Tools — What Bob Doesn't Have

### 2.1 Dedicated File Tools: Read, Edit, Write, Glob, Grep `[CC]` MISSING
Claude Code exposes individual file-system tools to the model:
- `FileReadTool` — read a file (separate from shell)
- `FileEditTool` — precise string-replacement edits (the `Edit` tool in this conversation)
- `FileWriteTool` — write full file contents
- `GlobTool` — find files by glob pattern
- `GrepTool` — search file contents by regex

These give the model faster, sandboxed file access without spawning a shell. They also generate structured approval requests for writes.

Bob routes everything through `shell.py` (Bash). This is functional but slower and less sandboxable.

**Fix**: Add dedicated tool handlers that map to Python `pathlib` + `re` operations; expose them to the model via the tool registry. Low risk, high leverage.

### 2.2 WebFetchTool `[CC]` MISSING
Claude Code has a `WebFetchTool` that lets the model fetch a URL and read its content (converted to markdown). Different from web search — this is for loading documentation, GitHub files, reference pages.

Bob has `WebSearchMode` in config and `web_search.rs` in Codex, but no URL fetch tool.

**Fix**: Add `WebFetchTool` using `httpx` async; convert HTML to markdown with `markdownify` or `html2text`. Integrate into tool registry when `web_search_mode != DISABLED`.

### 2.3 JavaScript REPL `[CX]` MISSING
Codex has a `js_repl` / `js_repl_reset` tool that gives the model an in-process JavaScript runtime (via Node.js or QuickJS). Useful for quick calculations, JSON manipulation, data transformations without spawning a full shell process.

**Fix**: Add `js_repl` tool using `subprocess` with `node -e` or a persistent Node.js child process.

### 2.4 NotebookEditTool — Jupyter Support `[CC]` MISSING
Claude Code can read and edit Jupyter `.ipynb` notebooks cell-by-cell via `NotebookEditTool`. For data science workflows this is essential.

**Fix**: Add `notebook_edit` and `notebook_read` tools using `nbformat` library.

### 2.5 Task Management Tools `[CC]` MISSING
Claude Code exposes a full task-tracker to the model:
- `TaskCreate` — create a task with title, description, status
- `TaskUpdate` — mark in_progress / completed
- `TaskList` — list all tasks  
- `TaskGet` — get task details
- `TaskOutput` — append output to a task
- `TaskStop` — cancel a running task
- `TodoWrite` — write a markdown todo list

These allow the model to structure multi-step work, track progress, and communicate state to the user.

Bob has `update_plan.py` (plan tool) which is related but less granular.

### 2.6 AskUserQuestionTool `[CC]` PARTIAL
Claude Code has `AskUserQuestionTool` — the model explicitly asks a structured clarifying question that interrupts the flow and waits for a typed answer. Different from the approval prompt.

Bob has `request_user_input.py` which does something similar, but the TUI rendering of it isn't distinct from the approval flow.

### 2.7 SleepTool `[CC]` MISSING
Allows the model to wait N seconds (e.g., waiting for a build to finish, polling for a file). Simple but useful.

### 2.8 EnterPlanMode / ExitPlanMode `[CC]` MISSING  
Claude Code has a special "plan mode" where the model can only read and plan — no writes/executions allowed. The model builds a plan, presents it, and only exits plan mode when the user approves. This prevents runaway changes on complex tasks.

Bob has `update_plan.py` for planning but no locked plan-mode gate.

### 2.9 Git Worktree Tools `[CC]` MISSING
`EnterWorktreeTool` / `ExitWorktreeTool` — Claude Code can spin up isolated git worktrees to work on tasks without touching the main working tree. Huge for multi-task parallel work.

### 2.10 ScheduleCronTool / RemoteTriggerTool `[CC]` MISSING
Claude Code supports scheduling recurring agent tasks via cron syntax and triggering remote agents. Related to the `/schedule` skill.

### 2.11 LSPTool — Language Server Integration `[CC]` MISSING
Claude Code has `LSPTool` that connects to Language Servers (TypeScript, Python, Rust, etc.) to get:
- Type information and hover docs
- Diagnostics / errors without running code
- Go-to-definition results
- Code actions / quick fixes

This dramatically improves code editing quality. Not trivial to implement but high value.

### 2.12 BriefTool `[CC]` MISSING
Switches the model to a concise "brief" output mode — short, action-focused responses. Toggled via `/brief` command. Bob has `Personality` in config which covers this partially.

---

## 3. Agent & Multi-Agent Capabilities

### 3.1 Built-in Specialized Sub-agents `[CC]` PARTIAL
Claude Code ships with built-in subagent templates:
- `explore` — fast filesystem exploration agent
- `plan` — software architect / planning agent  
- `general-purpose` — research and multi-step agent
- `verification` — runs tests and verifies changes
- `claude-code-guide` — answers questions about Claude Code itself
- `statusline-setup` — configures the status line

Bob has multi-agent infrastructure (`tools/multi_agent/`) and `spawn_agent`, but no built-in curated agent templates with pre-defined system prompts.

**Fix**: Add built-in agent definitions in `bob/core/agent/` — at minimum: `explore`, `plan`, `verify`. These are just curated system prompts + tool subsets.

### 3.2 Agent Color Coding `[CC]` MISSING
When multiple subagents are running, Claude Code renders each agent's output in a **distinct color** (red, blue, green, yellow, purple, orange, pink, cyan) so you can visually distinguish parallel work.

Bob's multi-agent output renders all agents identically.

**Fix**: Add an `agentColorManager` that assigns colors from a palette. Each `spawn_agent` call gets the next color; tool output from that agent is prefixed with that color.

### 3.3 Agent Memory Snapshots `[CC]` MISSING
Claude Code's `AgentTool` captures memory snapshots between agent runs — what was learned, what context is preserved — enabling coherent multi-session agent chains.

### 3.4 Parallel Tool Execution `[CC+CX]` MISSING
Both Claude Code and Codex can run multiple tool calls **in parallel** when the model requests them simultaneously (OpenAI parallel tool calls / Anthropic tool_use batches).

Bob's `turn.py` likely processes tool calls sequentially. For complex tasks with multiple independent operations, this is a significant speed difference.

**Fix**: In `bob/core/turn.py`, when tool calls arrive in a batch, use `asyncio.gather()` to execute non-conflicting tools concurrently.

---

## 4. Slash Commands — Missing from Bob

Bob has ~35 slash commands. Claude Code has 70+. Missing high-value ones:

| Command | What It Does | Priority |
|---------|-------------|----------|
| `/commit` | Stage, write message, and commit current changes via AI | High |
| `/branch` | Create/switch git branches | High |
| `/help` | Rich formatted help listing all commands | High |
| `/model` | Change model at runtime | High |
| `/effort` | Change reasoning effort (low/medium/high) | High |
| `/vim` | Toggle vi input mode | Medium |
| `/theme` | Switch color theme | Medium |
| `/cost` | Show session cost breakdown | Medium |
| `/usage` | Show token usage stats | Medium |
| `/export` | Export conversation to file | Medium |
| `/context` | Add a URL or file to context | Medium |
| `/config` | Show/edit config at runtime | Medium |
| `/hooks` | List/manage hooks | Medium |
| `/output-style` | Toggle brief/normal/verbose | Low |
| `/issue` | Create a GitHub issue from conversation | Low |
| `/pr_comments` | Review PR comments | Low |
| `/summary` | Summarize the current session | Low |
| `/memory` | Show/edit memory file | Low |
| `/stats` | Session statistics | Low |
| `/rewind` | Undo last N turns | Low |
| `/share` | Share session as a URL | Low |
| `/review` | Trigger a code review agent | Low |
| `/session` | Show session metadata | Low |

---

## 5. Configuration — Missing Options

Bob's config is rich but missing some things both peers have:

| Option | Codex | Claude Code | Bob |
|--------|-------|-------------|-----|
| Output style (brief/verbose) | ✓ | ✓ | ✗ |
| Auto-compact threshold (tokens) | ✓ | ✓ | PARTIAL (field exists, not tested) |
| Prompt caching enable/disable | ✓ | ✓ | ✗ |
| Context window max tokens cap | ✓ | ✓ | ✗ |
| Per-tool approval granularity | ✓ | ✓ | PARTIAL |
| MCP server auth tokens | ✓ | ✓ | ✗ |
| Git commit attribution | CX | ✗ | ✗ |
| Network proxy settings | CX | ✗ | ✗ |
| Response streaming on/off | ✓ | ✓ | always on |
| Managed feature flags | CX | ✓ | ✗ |
| Shell detection (bash/zsh/fish/pwsh) | ✓ | ✓ | ✗ (hardcoded) |

---

## 6. Performance & Speed

### 6.1 Prompt Caching `[CC+CX]` MISSING
Both Claude Code and Codex explicitly set `cache_control` on system prompts and long context blocks so the API can cache them between turns. This can cut costs by 90% and latency by 30% on long sessions.

Bob sends the full context every turn with no cache hints.

**Fix**: In `bob/core/turn.py` / `bob/client/openai_client.py`, add `cache_control: {"type": "ephemeral"}` to system message and static context blocks (AGENTS.md content, instructions).

### 6.2 Parallel Tool Execution
Already listed in §3.4 — critical for speed on multi-file operations.

### 6.3 Context Truncation & Turn Rollout `[CC+CX]` PARTIAL
Both peers have sophisticated context management:
- **Codex**: `thread_rollout_truncation.rs` + `context_manager/` — tracks token counts per turn, intelligently truncates old tool outputs while keeping key context
- **Claude Code**: `VirtualMessageList` for efficient rendering + context compaction that summarizes instead of truncating

Bob has `bob/core/context_manager.py` and `bob/core/compact.py` — the infrastructure exists, but whether it's wired to auto-trigger at thresholds needs verification.

### 6.4 Session Pre-warm `[CX]` MISSING
Codex has `session_startup_prewarm.rs` — it pre-warms the model connection and prefetches context at startup so the first response is faster.

### 6.5 Turn Timing Telemetry `[CX]` MISSING
Codex tracks per-turn timing (`turn_timing.rs`, `turn_metadata.rs`) and can show time-to-first-token, total latency, etc. Useful for debugging slow turns.

---

## 7. Security & Sandbox

### 7.1 Windows Sandbox Levels `[CC+CX]` PARTIAL
Codex has a detailed Windows sandbox with `windows_sandbox_read_grants.rs` — granular control over which paths the model can read/write, separate from the sandbox_mode toggle.

Bob has `WindowsSandboxLevel` in config but `bob/sandbox/windows.py` may not enforce fine-grained path grants.

### 7.2 Network Approval `[CX]` MISSING
Codex has `network_approval.rs` — when the model tries to make a network request (beyond approved domains), it prompts for approval just like exec approval.

Bob has `network_access: bool` but no per-request network approval flow.

### 7.3 Command Canonicalization `[CX]` PARTIAL
Codex's `command_canonicalization.rs` normalizes shell commands before showing them to the user (e.g. unwrapping `cmd /c`, `powershell -Command`, resolving aliases). Bob has a partial version in `interface.py` (`_format_command`) but it's UI-only — the core approval system sees the raw command.

---

## 8. Session & Memory

### 8.1 Session Export `[CC+CX]` MISSING
Both Claude Code (`/export`) and Codex can export full session transcripts as Markdown or JSON. Bob has rollout recording (`bob/rollout/recorder.py`) but no export-to-file slash command.

### 8.2 Session Sharing `[CC]` MISSING
Claude Code can share a session as a URL (via `/share`). Not critical but worth noting.

### 8.3 Turn Diff Tracking `[CX]` MISSING
Codex tracks which files were modified in each turn (`turn_diff_tracker.rs`) and surfaces this as a per-turn diff summary. Bob doesn't track the "what changed this turn" summary.

### 8.4 Rewind / Undo Turns `[CC]` MISSING
Claude Code's `/rewind` command can undo the last N turns — removing the tool calls and responses from history. Very useful when the model goes in a wrong direction. Would require Bob to track turn boundaries in the rollout.

---

## 9. Integrations

### 9.1 Git Integration `/commit`, `/branch`, `/pr_comments` `[CC]` MISSING
Bob has `/diff` but Claude Code goes much further:
- `/commit` — AI writes the commit message, runs git commit
- `/branch` — create branch, optionally tied to an issue
- `/pr_comments` — pull in PR review comments as context
- `/autofix-pr` — auto-fix a PR based on review comments
- `/issue` — create a GitHub issue from the current task

### 9.2 IDE Bridge `[CC]` MISSING
Claude Code has a bridge mode that connects to VS Code / JetBrains — reads open files, current selection, problems panel. Bob has an `app_server` for IDE integrations but no active IDE bridge tool exposed to the model.

### 9.3 Slack / GitHub App Install `[CC]` MISSING
Claude Code has `/install-github-app` and `/install-slack-app`. Not core functionality but shows the integration depth.

### 9.4 Web Search Tool `[CC+CX]` PARTIAL
Bob has `WebSearchMode` in config and the config schema references it, but whether the web_search tool is actually registered and callable in the current agent loop needs verification. Codex uses `web_search.rs`, Claude Code has `WebSearchTool`. Confirm Bob's is wired end-to-end.

---

## 10. Quality of Life — Small but Visible

| Feature | CC | CX | Bob |
|---------|----|----|-----|
| `•` assistant message color (brand orange, not default) | ✓ | ✗ | ✗ |
| Thinking/reasoning block display (collapsible) | ✓ | ✓ | PARTIAL |
| Syntax highlighted code blocks in responses | ✓ | ✗ | ✗ |
| Word-wrap at terminal width for long lines | ✓ | ✓ | ✗ |
| Command history persistence across sessions | ✓ | ✓ | ✗ (InMemoryHistory) |
| `/help` with formatted command list | ✓ | ✓ | ✗ |
| Ctrl+R reverse history search | ✓ | ✓ | PARTIAL (prompt_toolkit) |
| Autocomplete for `@filename` mentions | ✓ | ✗ | ✗ |
| Autocomplete for `#tool` mentions | ✓ | ✗ | ✗ |
| Spinner label shows current tool name | ✓ | ✓ | ✗ (shows "Thinking…" always) |
| Error messages include file:line context | ✓ | ✓ | ✗ |
| Output truncation notice shows hidden line count | ✓ | ✓ | ✓ |
| Welcome screen "Recent activity" from real sessions | ✓ | ✗ | ✗ (hardcoded "No recent activity") |

---

---

## 11. Voice & Realtime Conversation

### 11.1 Voice Input / STT `[CC+CX]` MISSING
Both Claude Code and Codex have full voice-to-text support:
- Real-time audio streaming from microphone
- STT (speech-to-text) transcription fed as prompt text
- Audio device selection (microphone/speaker)
- Voice mode toggle via `/voice` (Claude Code)

Bob has no audio input/output at all.

**Fix**: Wire up `openai.audio.speech` (TTS) and `openai.audio.transcriptions` (STT) via a `/voice` toggle command. Could use `sounddevice` + `openai` Whisper endpoint. Lower priority than code features but important for accessibility.

### 11.2 Realtime Conversation Protocol `[CC+CX]` MISSING
Claude Code and Codex both support OpenAI's Realtime API — continuous two-way audio with the model, without the turn-based prompt loop. Bob has `enable_realtime: bool` in config but it's wired to nothing.

---

## 12. Rich Output Rendering

### 12.1 Streaming Markdown in Responses `[CC+CX]` MISSING
Both Claude Code (React/Ink renderer) and Codex (`markdown_render.rs` — 41KB) render the model's responses with **live markdown formatting**:
- Bold (`**text**`) rendered bold in terminal
- Code fences with syntax highlighting
- Bullet lists with proper indentation
- Headers as bold+underline lines
- Inline code with background highlight

Bob streams raw text with no markdown rendering — the `•` prefix is the only formatting.

**Fix**: Parse markdown in `TextDeltaEvent` using `rich.markdown.Markdown` or a streaming state machine. At minimum handle bold, inline code, and code fences.

### 12.2 Colored Diff Rendering `[CC+CX]` MISSING
Codex has a dedicated `diff_render.rs` (97KB). Claude Code has a `colorDiff.ts` and structured diff component. Both render:
- `+` lines in green with green background
- `-` lines in red with red background
- `@@` hunk headers in cyan/dim
- Context lines dim

Already listed in §1.2 but worth noting it's a dedicated large module in both peers — not an afterthought.

### 12.3 Reasoning / Thinking Block Display `[CC+CX]` PARTIAL
Claude Code shows thinking blocks as collapsible sections with a shimmer animation while thinking. Codex streams reasoning summaries. Bob has `show_reasoning: bool` in config but the `_consume_events` loop has no handler for `ReasoningDeltaEvent` or `ReasoningSummaryEvent`.

**Fix**: Add event handlers for reasoning events and render them collapsed by default:
```
  ⟨thinking⟩ 847 tokens  [expand]
```

---

## 13. Diagnostics & Developer Tools

### 13.1 `/doctor` Diagnostic Screen `[CC]` MISSING
Claude Code's `/doctor` command runs a full diagnostic check:
- API key validity
- Network connectivity
- Config file syntax
- Permission state
- Version checks
- MCP server status
- Memory system health

Bob has no equivalent. Debugging issues requires reading logs manually.

**Fix**: Add `SlashCommand.DOCTOR` that runs async checks and prints a color-coded report. Highly useful for users troubleshooting setup issues.

### 13.2 `/cost` and `/usage` Commands `[CC]` MISSING
Claude Code tracks and displays:
- Per-session token spend (input/output separately)
- Estimated dollar cost
- Context window % used
- Rate limit fill bar

Bob has `CostEstimateEvent` and `TokenBudgetEvent` in the event protocol but discards both in the UI.

**Fix**: Accumulate token counts and cost from events. Display inline after each turn (§1.1 above) and add `/cost` / `/usage` slash commands to show session totals.

### 13.3 Frame Rate Limiting `[CX]` MISSING
Codex has `frame_rate_limiter.rs` — throttles terminal redraws to ~60fps so streaming output doesn't hammer the terminal and cause flickering or CPU waste. On fast model responses Bob can output characters faster than the terminal can render them cleanly.

---

## 14. Advanced Sandbox Architecture

### 14.1 macOS Seatbelt Policy Files `[CX]` MISSING
Codex ships `.sbpl` policy files:
- `seatbelt_base_policy.sbpl` — base sandbox
- `seatbelt_network_policy.sbpl` — network isolation
- `restricted_read_only_platform_defaults.sbpl` — read-only mode

Bob's `sandbox/macos.py` exists but likely calls subprocess without a real Seatbelt profile. True sandboxing requires the `sandbox-exec` syscall with a compiled policy.

### 14.2 Linux bubblewrap + Landlock `[CX]` MISSING
Codex uses `bwrap` (bubblewrap) for container-level isolation on Linux, plus `Landlock` LSM for filesystem access control at the kernel level. Bob's `sandbox/linux.py` needs to be verified — it may be a stub.

### 14.3 Shell Escalation Detection `[CX]` MISSING
Codex has a `shell-escalation` module that detects when a tool tries to escape the sandbox via shell metacharacters, `sudo`, `su`, `chroot`, `nsenter`, etc. Bob has no equivalent detection.

---

## 15. Models & API

### 15.1 Model Catalog `[CX]` MISSING
Codex ships `models.json` (252KB) — a comprehensive registry of all supported models with:
- Context window sizes
- Pricing per token
- Feature flags (supports vision, tools, reasoning, etc.)
- Recommended defaults per use case

Bob hardcodes `model: str = "gpt-5.1-codex-mini"` in config with no model metadata.

**Fix**: Add a `models.json` catalog (or fetch dynamically via `/v1/models`). Use it to display model capabilities, context limits, and cost estimates.

### 15.2 Prompt Caching Headers `[CC+CX]` MISSING
Already in §6.1 — worth repeating as the agent confirmed both peers do this. The OpenAI API supports `cache_control` on messages. Anthropic uses `cache_control: {"type": "ephemeral"}`. This is a **free 70-90% cost reduction** on long sessions with stable system prompts.

### 15.3 Extended Thinking / Ultrathink `[CC]` MISSING
Claude Code has full extended thinking support:
- Budget token configuration
- Adaptive thinking based on query complexity
- Rainbow visualization for thinking blocks
- Trigger keyword detection (`ultrathink`, `think hard`, etc.)
- Streaming thinking deltas
- Collapsible thinking block display

---

## 16. Comparison Summary Table

| Feature Category | Bob V2 | Codex | Claude Code |
|---|---|---|---|
| Slash commands | ~35 impl'd of 52 defined | 67 | 105+ |
| Model tools available | 9 | 13 | 46 |
| Multi-agent system | Stub only | Full Rust impl | Extensive |
| Reasoning modes | Basic effort | Full | Ultrathink |
| Voice / Realtime | None | Partial | Full STT/TTS |
| Native sandboxing | Basic modes | Seatbelt + bwrap + Landlock | Toggle only |
| Vi/vim input mode | None | Partial | Full |
| Theme system | None | Yes | 6 themes |
| Memory system | Phase1/2 basic | Yes | Extensive |
| Skills system | Manager exists | Registry | Advanced |
| Markdown rendering | None | 41KB renderer | Yes |
| Diff rendering | None | 97KB renderer | Yes |
| Prompt caching | None | Yes | Yes |
| Parallel tool execution | No | Yes | Yes |
| Token/cost display | None | Yes | Yes |
| Web fetch | None | Partial | Yes |
| LSP integration | None | None | Yes (LSPTool) |
| IDE bridge | None | None | Yes (VS Code) |
| Voice support | None | Partial | Full |
| Jupyter notebooks | None | None | Yes (NotebookEditTool) |
| Diagnostics (/doctor) | None | None | Yes |
| Analytics/telemetry | None | Partial | Yes |
| Session sharing | None | None | Yes |
| Git worktrees | None | None | Yes |
| Persistent history | ✓ (just added) | Yes | Yes |

---

## Quick Win Priority List (Do These First)

**Already done this session:**
- ✓ Brand-orange `•` for assistant output (`\033[38;2;215;119;87m`)
- ✓ Persistent command history (`FileHistory` → `~/.bob/history`)
- ✓ Exact Anthropic brand color in welcome screen (24-bit RGB)

**Next — low effort, high visibility:**

1. **Token + cost display after each turn** — 1 hour, data already available in `TurnEndedEvent`
2. **`/help` command** — render COMMAND_DESCRIPTIONS nicely — 30 minutes
3. **`/model` slash command** — change model at runtime — 1 hour
4. **`/effort` slash command** — change reasoning effort at runtime — 30 minutes
5. **Spinner shows current tool name** — pass tool label to spinner — 30 minutes
6. **Reasoning block display** — add handler for `ReasoningDeltaEvent` — 1 hour
7. **`/doctor` diagnostic command** — check API, config, MCP — 2 hours
8. **Parallel tool execution** with `asyncio.gather` in `turn.py` — 2 hours, big speed win
9. **Colored patch/diff output** in `_print_tool_output` — 2 hours
10. **Prompt caching headers** on system message — 1 hour, **reduces cost 70%+ on long sessions**
