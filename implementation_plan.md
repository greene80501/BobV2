# Bob V2 — Remaining Implementation Work

Everything listed here is not yet working end-to-end. Items marked **[data done]** have a
backend/data layer built but no user-visible wiring yet.

---

## 1. Terminal UI & Prompt Experience

**1.1 Token/cost status line** [data done — analytics tracker has the data]
After each turn, render a dim one-liner below the response:
  claude-sonnet-4-5  ·  1,234 in  456 out  ·  $0.018  ·  12% ctx  ·  2,341ms
Wire `session.analytics.format_last_turn_status(model, context_window)` into the TUI's
`_consume_events` handler when it sees `TurnEndedEvent`. Context window comes from
`catalog.get_context_window(model)`.

**1.2 Colored diff output on patch**
When `apply_patch` runs, render a colored unified diff instead of silence:
  ● Patch(src/main.py)
  ⎿  - old line       (red)
     + new line       (green)
In `_print_tool_output` / `ExecCompletedEvent`, detect apply_patch calls and parse the
patch argument. Color `+` lines green (`\033[32m`), `-` lines red (`\033[31m`), `@@`
headers cyan.

**1.3 Vi/vim input mode**
`/vim` slash command is defined in the enum but never dispatched. Fix:
- Add dispatch case in `interface.py` slash command handler.
- Toggle a session-level `_vi_mode: bool` flag.
- Re-create `PromptSession` with `vi_mode=True` when toggled on.

**1.4 Multi-line input with Shift+Enter**
`PromptSession` is single-line. Fix:
- Create a custom `KeyBindings` object where `Enter` submits and `Shift+Enter`
  inserts `\n`.
- Pass `multiline=True` and the custom bindings to `PromptSession`.

**1.5 Theme system**
`no_color` config field exists but TUI hardcodes dark ANSI colors. Implement:
- Add `theme: str` to `BobConfig` (values: `dark`, `light`, `no-color`).
- Create a `Theme` dataclass with color constants (BRAND, DIM, BOLD, ERROR, etc.).
- Pass active theme into `interface.py`; all color codes reference theme, not literals.
- Wire `/theme` slash command to switch and persist to config.

**1.6 Status line hooks**
`bob/hooks/runner.py` exists but output is never surfaced in the UI. Wire:
- After each turn, run configured `post_turn` hooks.
- Display stdout of hooks in a dim status line below the response.
- Add hook config section to `~/.bob/config.toml` schema.

**1.7 Image attachment in TUI**
`view_image.py` tool exists but there's no way to attach an image from the prompt.
Implement `@image` syntax:
- In the prompt completer, detect `@` prefix and offer file path completion.
- When input is submitted, scan for `@/path/to/image.png` tokens.
- Convert matched paths to `ImageUserInput` items passed to `UserTurnOp`.

---

## 2. Tools — Missing or Incomplete

**2.1 Task management system**
`todo_write.py` and `update_plan.py` exist but there's no structured task tracker
the model can manipulate as discrete objects. Build:
- `TaskCreate(title, description)` → returns task_id
- `TaskUpdate(task_id, status)` → status: pending / in_progress / completed / cancelled
- `TaskList()` → returns all tasks with status
- `TaskGet(task_id)` → returns single task details
- `TaskOutput(task_id, text)` → append output log to a task
- `TaskStop(task_id)` → cancel a running task
Store in a SQLite table at `~/.bob/tasks.db`. Register all in `session.py`.

**2.2 AskUserQuestion distinct rendering**
`request_user_input.py` exists but its TUI rendering is identical to the approval flow.
Fix:
- Detect `UserInputRequestEvent` separately in `_consume_events`.
- Render with a distinct visual style (e.g. `? ` prefix in blue, inline input box).
- Separate code path from the `ExecApprovalRequestedEvent` handler.

**2.3 Locked Plan Mode gate**
`plan_mode.py` and `session._plan_mode` exist as a simple toggle. The missing piece:
- When `_plan_mode == True`, block tool execution entirely (not just filter specs).
- When model calls `exit_plan_mode`, surface the plan to the user for approval.
- Only unlock write tools after explicit user confirmation (`y` / `n` prompt).
- Show plan summary in the TUI before the approval prompt.

**2.4 Git Worktree tools**
No worktree isolation exists. Build:
- `EnterWorktreeTool(branch_name)` → runs `git worktree add`, sets session cwd to
  new worktree path, records original cwd.
- `ExitWorktreeTool()` → removes worktree, restores original cwd.
- Register both in `session.py`. Add `worktree_path` to `ToolContext`.

**2.5 Cron/Schedule tools**
No scheduling system exists. Build:
- `ScheduleCronTool(cron_expr, task_description)` → saves schedule to
  `~/.bob/schedules.db`, returns schedule_id.
- `RemoteTriggerTool(schedule_id)` → manually fires a scheduled task.
- A background runner (separate process or thread) that executes due tasks.

**2.6 LSP integration**
No language server connection. Build:
- `LSPTool` that starts/connects to the appropriate language server for the current
  file type (pyright for Python, tsserver for TS, rust-analyzer for Rust).
- Expose: `lsp_hover(file, line, col)`, `lsp_diagnostics(file)`,
  `lsp_definition(file, line, col)`, `lsp_references(file, line, col)`.
- Use `pygls` or direct subprocess JSON-RPC to the LSP.

**2.7 BriefTool / output-style toggle**
`Personality` enum in config covers this partially. Complete:
- Add `OutputStyle` enum: `brief`, `normal`, `verbose`.
- Inject current style into the system prompt (brief: "Be extremely concise. One
  sentence answers where possible." etc.).
- Wire `/output-style` slash command to toggle and persist.
- Add `/brief` as an alias.

---

## 3. Agent & Multi-Agent

**3.1 Built-in curated sub-agent templates**
`agent_templates.py` has tool restriction lists but no identity/system prompts.
Build dedicated templates with full system prompts for:
- `explore` — fast filesystem/codebase explorer, read-only, returns structured findings
- `plan` — software architect, produces implementation plans, no writes
- `verify` — runs tests, checks diffs, validates changes, reports pass/fail
- `write` — focused implementation agent, given a specific task and file scope
- `review` — code reviewer, reads PR diff, produces structured review comments
Each template: name, description, system_prompt, allowed_tools list, default model.

**3.2 Agent memory snapshots**
No mechanism to capture what a sub-agent learned between runs. Build:
- At sub-agent shutdown, extract a "memory snapshot" (summary of findings, key facts,
  files modified) from the agent's final context.
- Store snapshot keyed by agent name + session in `~/.bob/agent_memory.db`.
- On next spawn with same agent name, inject prior snapshot into context.

**3.3 Parallel tool execution**
`turn.py` executes tool calls sequentially in a `for tc in tool_calls` loop. Fix:
- Classify tools as concurrency-safe (read-only: read_file, glob, grep, web_fetch)
  vs. unsafe (write_file, edit_file, shell, apply_patch).
- When a batch of tool calls arrives, group by safety class.
- Execute safe tools with `asyncio.gather()`.
- Execute unsafe tools sequentially after safe ones complete.
- Requires care around approval flow — approval must still happen before execution.

---

## 4. Slash Commands — Not Dispatched

All of the following are defined in `SlashCommand` enum in `slash_commands.py` but have
no handler in `interface.py`'s dispatch block:

**4.1 /cost**
Display session cost from `session.analytics.format_session_cost()`. Also show model
catalog pricing for current model from `catalog.get_pricing(model)`.

**4.2 /usage**
Display full token breakdown: session input tokens, output tokens, total, by-turn
history. Pull from `await session._analytics_db.session_totals(session.session_id)`.

**4.3 /vim**
Toggle vi input mode. Re-create `PromptSession(vi_mode=True/False)`. See §1.3.

**4.4 /theme**
Switch color theme. See §1.5.

**4.5 /export**
Export current session conversation to a Markdown file. Walk
`session.context_manager.raw_items()`, format as Markdown, write to
`~/bob-export-{timestamp}.md`. Print confirmation with path.

**4.6 /context**
Add a file or URL to the next turn's context:
- `/context path/to/file.py` → reads file, prepends as a context item.
- `/context https://example.com/docs` → fetches URL, prepends as context.
- Show what's currently attached to context.

**4.7 /config**
Show current `~/.bob/config.toml` contents in a formatted table. Optionally open in
`$EDITOR`. Show active overrides (CLI flags, env vars).

**4.8 /hooks**
List configured hooks from config. Show: event type, command, last run status.
Allow adding/removing hooks interactively.

**4.9 /output-style**
Toggle between `brief`, `normal`, `verbose`. See §2.7.

**4.10 /issue**
Open a GitHub issue from the current task:
- Prompt for title + body (pre-filled from conversation summary).
- Run `gh issue create` via shell tool.
- Print the created issue URL.

**4.11 /pr_comments**
Pull PR review comments as context:
- Prompt for PR number or URL.
- Run `gh pr view {n} --comments --json` to fetch.
- Inject as a context item for the next turn.

**4.12 /memory**
Show/edit the Bob memory file (`~/.bob/memory.md`):
- `/memory` → print current contents.
- `/memory edit` → open in `$EDITOR`.
- `/memory clear` → wipe and confirm.

**4.13 /stats**
Show session statistics: turns taken, tools called (by name + count), total tokens,
total cost, avg latency per turn. Pull from `session.analytics` and
`await session._analytics_db.session_totals()`.

**4.14 /share**
Export session as a shareable artifact (local file or URL). Minimum viable: write
a self-contained HTML file of the conversation transcript.

**4.15 /session**
Show metadata about the current session: session_id, start time, model, cwd, tool
count, context size (tokens), sandbox mode.

**4.16 /rewind**
Undo last N turns. `UndoOp` exists in protocol and `drop_last_n_user_turns()` exists
in context_manager. Wire: parse `/rewind N`, submit `UndoOp(n=N)` to session. Clear
the corresponding rollout entries from the recorder.

**4.17 /doctor**
Run diagnostic checks and print a color-coded report:
- API key present and valid (test with a minimal API call)
- Network connectivity (ping api.openai.com or configured base_url)
- Config file exists and parses cleanly
- MCP servers reachable (if configured)
- Model catalog present (`~/.bob/llm_database.db`)
- Analytics DB accessible (`~/.bob/analytics.db`)
- Sandbox mode and path grants
- Bob version and Python version

---

## 5. Configuration — Missing Options

Add these fields to `BobConfig` in `bob/config/schema.py` and load from
`~/.bob/config.toml`:

- `output_style: OutputStyle = OutputStyle.NORMAL` — brief / normal / verbose
- `prompt_caching: bool = True` — enable cache_control headers (see §6.1)
- `max_context_tokens: int = 0` — 0 = use model default; set to cap context window
- `mcp_auth_tokens: dict[str, str] = {}` — per-server auth tokens for MCP
- `git_commit_attribution: str = ""` — Co-authored-by line appended to AI commits
- `network_proxy: str = ""` — HTTP proxy URL for all outbound requests
- `stream_responses: bool = True` — False = buffer full response before display
- `feature_flags: dict[str, bool] = {}` — named feature toggles
- `shell: str = ""` — override shell detection (bash/zsh/fish/pwsh); auto-detect if empty
- `auto_compact_threshold: float = 0.8` — compact when context exceeds this fraction

---

## 6. Performance

**6.1 Prompt caching**
No `cache_control` headers are sent. This costs 70–90% more than necessary on long
sessions. Fix in `bob/llm/client.py` (`_to_chat_messages` or the kwargs builder):
- Add `cache_control: {"type": "ephemeral"}` to the system message.
- Add `cache_control` to long static context blocks (AGENTS.md content, instructions).
- Anthropic: add `cache_control` field to message content parts.
- OpenAI: no equivalent yet — skip for OpenAI models.

**6.2 Session pre-warm**
First response is cold (TCP + TLS + model warmup). Fix:
- In `session.start()`, fire a background task that sends a minimal keepalive request
  to the API endpoint immediately on startup.
- Don't await it — just let it run so the connection is warm by the time the user
  submits their first message.

**6.3 Frame rate limiting**
Fast streaming can flood the terminal. Fix:
- In the TUI's event consumption loop, track the last render time.
- Batch `TextDeltaEvent` chunks that arrive within 16ms (60fps) and render them
  together in one `print()` call.
- Use `asyncio.sleep(0)` between batches to yield to the event loop.

---

## 7. Security & Sandbox

**7.1 Windows sandbox path grants**
`WindowsSandboxLevel` is in config but `bob/sandbox/windows.py` doesn't enforce
fine-grained read/write path grants. Implement:
- Parse `sandbox_read_dirs` and `sandbox_write_dirs` from config.
- Before executing a shell command, check that the target path falls within granted
  directories.
- Reject with a clear error message if not.

**7.2 Network approval flow**
`network_access: bool` in config is all-or-nothing. Build per-request approval:
- Intercept outbound HTTP calls from `web_fetch` and `web_search` tools.
- Check domain against an approved-domains list in config.
- If not approved, emit `NetworkApprovalRequestedEvent` and pause — same flow as
  `ExecApprovalRequestedEvent`.
- User can approve once, approve always, or deny.

**7.3 Command canonicalization in approval**
`_format_command` in `interface.py` normalizes for display only. The approval system
sees the raw command. Fix:
- In `exec_policy.py` / `needs_approval()`, normalize the command before matching
  trusted patterns (unwrap `cmd /c`, `powershell -Command`, resolve `./` paths).
- This prevents approval bypasses via shell metacharacter wrapping.

**7.4 macOS Seatbelt policy files**
`sandbox/macos.py` likely calls subprocess without a real Seatbelt profile. Build:
- Write `.sbpl` policy files: base policy, network isolation policy, read-only mode.
- Call `sandbox-exec -f policy.sbpl` when running commands in sandbox mode.
- Ship the `.sbpl` files as package data.

**7.5 Linux bubblewrap + Landlock**
`sandbox/linux.py` is likely a stub. Build:
- Use `bwrap` (bubblewrap) for container-level isolation: bind-mount workspace,
  block /proc, /sys, network namespace.
- Use `Landlock` via ctypes for kernel-level filesystem access control.
- Fall back gracefully if bwrap is not installed.

**7.6 Shell escalation detection**
No detection of sandbox-escape attempts. Add to `exec_policy.py`:
- Reject or require explicit approval for: `sudo`, `su`, `chroot`, `nsenter`,
  `unshare`, `ptrace`, `LD_PRELOAD`, shell metacharacters in trusted-command paths.
- Log all escalation attempts.

---

## 8. Session & Memory

**8.1 Session export**
Rollout recorder writes JSONL but there's no `/export` command that produces a
human-readable file. Implement:
- Walk `session.context_manager.raw_items()`.
- Format as Markdown: user turns as `**You:**`, assistant turns as `**Bob:**`,
  tool calls as code blocks.
- Write to `~/bob-session-{timestamp}.md`.
- Print path and byte size.

**8.2 Session sharing**
No `/share` mechanism. Minimum viable:
- Generate a self-contained HTML file with inline CSS rendering the conversation.
- Open it in the default browser (`webbrowser.open()`).
- Future: upload to a pastebin/gist and return URL.

**8.3 Turn diff tracking**
No record of which files changed in each turn. Build:
- Before each turn, snapshot a hash of all files in `session.cwd` (or track via
  `write_file`/`edit_file`/`apply_patch` calls).
- After the turn, compute which files changed.
- Store as a per-turn diff summary in the analytics DB.
- Surface in `/stats` and the turn status line.

**8.4 Rewind/undo**
`UndoOp` is in the protocol, `drop_last_n_user_turns()` is in context_manager, but
`/rewind N` isn't wired. See §4.16. Also:
- Clear the corresponding rollout file entries so a resumed session doesn't replay
  the undone turns.
- Reset analytics session accumulators for the dropped turns.

---

## 9. Integrations

**9.1 Full git integration**
`/diff` works. Missing:
- `/commit` — Bob writes the commit message (via a quick model call on the current
  diff), runs `git add -A && git commit -m "..."`. User can edit before confirm.
- `/branch` — create or switch branches: `/branch feature-xyz` runs
  `git checkout -b feature-xyz`.
- `/pr_comments` — see §4.11.
- `/issue` — see §4.10.
- `/autofix-pr` — fetch PR diff + review comments, feed to Bob as context, let Bob
  apply fixes automatically.

**9.2 IDE bridge tool**
`app_server/` exists for JSON-RPC but no tool is exposed to the model to read IDE
state. Build:
- `ide_get_open_files()` → list of open file paths in VS Code / JetBrains.
- `ide_get_selection()` → current selected text + file + line range.
- `ide_get_diagnostics()` → problems panel contents (errors, warnings).
- Requires the IDE extension to be running and connected to the app_server.

**9.3 Web search end-to-end verification**
`web_search.py` exists. Verify and fix:
- Confirm `web_search` is registered in `session._register_builtin_tools()` — it is,
  but test that it's actually callable by the model in a live session.
- Confirm DuckDuckGo API calls work without a key.
- Add a fallback (SerpAPI or Brave Search) when DDG is rate-limited.
- Wire `web_search_mode` config field to conditionally register the tool.

---

## 10. Quality of Life

**10.1 Syntax-highlighted code blocks**
Model responses stream as raw text. When a turn completes and `TextFinalEvent` fires,
re-render the full text through `rich.markdown.Markdown` with `rich.syntax.Syntax`
for code fences. Or render incrementally using a streaming Markdown state machine.

**10.2 Word-wrap at terminal width**
Long lines are not wrapped. Fix:
- Detect terminal width via `shutil.get_terminal_size()`.
- Wrap text at that width before printing each `TextDeltaEvent` delta.
- Update on terminal resize (listen for `SIGWINCH` on Unix).

**10.3 /help with formatted output**
`/help` is dispatched but renders a flat list. Replace with:
- Group commands by category (Session, Code, Config, Experimental, etc.).
- Use `rich.table.Table` or `rich.columns.Columns` for alignment.
- Show key bindings alongside each command.
- Include short descriptions from `COMMAND_DESCRIPTIONS` dict.

**10.4 @filename autocomplete**
No `@` mention system exists. Build:
- In the `PromptCompleter`, detect when input contains `@`.
- After `@`, complete with file paths relative to `session.cwd`.
- On submit, resolve `@path` tokens and attach file contents as context items.

**10.5 #tool mention autocomplete**
No `#tool` mention system. Build:
- In the `PromptCompleter`, detect `#` prefix.
- Complete with registered tool names from `session.tool_registry`.
- On submit, `#tool_name` injects a hint into the user message telling the model
  to prefer that tool.

**10.6 Spinner shows current tool name**
Spinner always shows "Thinking…". Fix:
- When `ToolCallStartedEvent` fires, update the spinner label to
  `"Running {tool_name}…"`.
- When `ToolCallCompletedEvent` fires, revert to `"Thinking…"` (if more turns remain)
  or clear entirely.
- Pass tool name into the spinner update method in `interface.py`.

**10.7 Error messages with file:line context**
Errors are plain strings. Improve:
- In `StreamErrorEvent` and `ErrorEvent` handlers, parse Python tracebacks if present.
- Highlight file paths and line numbers using `rich.traceback.Traceback`.
- For tool errors, include the tool name and input in the display.

**10.8 Welcome screen with real recent sessions**
Welcome screen shows hardcoded "No recent activity". Fix:
- On startup, query `session._session_index` for the 5 most recent sessions.
- Display: session name, date, model, turn count, cost.
- Make each entry selectable to resume that session directly.

---

## 11. Voice & Realtime

**11.1 Voice input / STT**
No audio input. Build (behind `/voice` toggle):
- Use `sounddevice` to capture microphone audio in a background thread.
- Stream to OpenAI Whisper (`openai.audio.transcriptions.create`) or a local
  Whisper model.
- Inject transcribed text as the prompt input.
- Show a "🎤 Recording…" indicator in the TUI.

**11.2 Realtime API conversation**
`enable_realtime: bool` is in config but wired to nothing. Build:
- Connect to OpenAI Realtime API via WebSocket.
- Bidirectional audio: capture mic → send audio chunks → receive audio response.
- Render transcript alongside audio playback.
- Toggle with `/realtime` command.

---

## 12. Rich Output Rendering

**12.1 Streaming markdown rendering**
Model responses stream as raw text — `**bold**`, ` ```code``` `, bullet lists all
appear literally. Fix:
- Implement a streaming Markdown state machine in `interface.py` (or use
  `rich.markdown.Markdown` on completed text).
- At minimum handle: **bold**, *italic*, `inline code`, ``` code fences ```,
  `# headers`, `- bullet lists`, `> blockquotes`.
- For code fences: detect language tag, use `rich.syntax.Syntax` for highlighting.

**12.2 Colored diff rendering**
No `+`/`-` line coloring anywhere in the TUI. See §1.2 — same fix applies both to
`apply_patch` preview and to `/diff` output.

**12.3 Reasoning block display**
`show_reasoning: bool` is in config. `ReasoningDeltaEvent` is in the protocol and
now emitted by `LiteLLMClient` (for Anthropic extended thinking). The TUI has no
handler. Fix:
- In `_consume_events`, add a case for `ReasoningDeltaEvent`.
- Buffer reasoning tokens separately from text tokens.
- Display collapsed by default: `⟨thinking⟩ 847 tokens` with expand option.
- When `show_reasoning = True` in config, stream inline with a dim prefix `│ `.

---

## 13. Diagnostics

**13.1 /doctor diagnostic screen**
No diagnostic runner exists. See §4.17 for full spec.

**13.2 /cost and /usage display** [data done — analytics tracker accumulates]
`session.analytics.format_session_cost()` is available. Wire:
- `/cost` slash command → call `format_session_cost()` + show per-model breakdown
  from `await session._analytics_db.model_breakdown(session.session_id)`.
- `/usage` slash command → show per-turn token table from
  `await session._analytics_db.recent_turns(20)`.
- Also wire `format_last_turn_status()` into the `TurnEndedEvent` handler so it
  displays after every response.

**13.3 Frame rate limiting**
See §6.3.

---

## 14. Sandbox — Advanced

**14.1 macOS Seatbelt policy files** — see §7.4
**14.2 Linux bubblewrap + Landlock** — see §7.5
**14.3 Shell escalation detection** — see §7.6

---

## 15. Models & API

**15.1 Model catalog integration** [catalog.py built — commands not wired]
`catalog.py` and `~/.bob/llm_database.db` exist. Wire:
- `/model` slash command → list available models from `catalog.list_models()`,
  let user pick, update `session.client.model` and `session.config.model`.
- At session start, log context window for current model from
  `catalog.get_context_window(model)` and use it for the `% ctx` display.
- In `/doctor`, report whether catalog is populated.
- Show pricing in `/cost` output via `catalog.get_pricing(model)`.

**15.2 Prompt caching headers** — see §6.1

**15.3 Extended thinking / Ultrathink**
`ReasoningDeltaEvent` now flows through `LiteLLMClient`. Complete the feature:
- Add `thinking_budget_tokens: int = 0` to `BobConfig` (0 = disabled).
- Detect trigger keywords in user input: `ultrathink`, `think hard`, `think deeply`,
  `think step by step` → automatically set a high budget.
- Pass `thinking: {"type": "enabled", "budget_tokens": N}` in the Anthropic request
  via `extra_params`.
- Render thinking blocks per §12.3.
- Add `/think` slash command to set budget for next turn only.

---

## Priority Order (highest impact first)

1. **§13.2 /cost + /usage display** — data is already tracked; just wire the TUI. 30 min.
2. **§1.1 Token/cost status line** — call `format_last_turn_status()` in `TurnEndedEvent` handler. 20 min.
3. **§12.1 Streaming markdown** — biggest visible UX gap. Use `rich.markdown.Markdown` on `TextFinalEvent`. 2–3 hrs.
4. **§3.3 Parallel tool execution** — `asyncio.gather()` in `turn.py` for read-only tools. 2 hrs.
5. **§6.1 Prompt caching** — add `cache_control` to system message in `client.py`. 1 hr. Free 70–90% cost cut.
6. **§1.2 Colored diff output** — parse apply_patch arg and colorize. 1–2 hrs.
7. **§12.3 Reasoning block display** — add `ReasoningDeltaEvent` handler in TUI. 1 hr.
8. **§10.6 Spinner shows tool name** — update spinner label in `ToolCallStartedEvent` handler. 20 min.
9. **§4.17 /doctor** — diagnostic runner. 2 hrs.
10. **§15.1 /model command** — list from catalog, let user pick. 1 hr.
11. **§4.16 /rewind** — wire `UndoOp` to `/rewind N`. 30 min.
12. **§1.3 Vi mode** — `PromptSession(vi_mode=True)`. 20 min.
13. **§1.4 Multi-line input** — custom `KeyBindings`. 30 min.
14. **§15.3 Extended thinking** — budget tokens + trigger detection. 2 hrs.
15. **§2.3 Parallel tool execution** — see item 4 above (same).
16. **§3.1 Curated sub-agent templates** — write system prompts for explore/plan/verify/write/review. 2 hrs.
17. **§2.1 Task management tools** — TaskCreate/Update/List/Get/Output/Stop. 3 hrs.
18. **§9.1 Git integration** — /commit, /branch, /autofix-pr. 3 hrs.
19. **§10.1 Syntax highlighted code blocks** — rich.syntax in output. 1 hr.
20. **§10.8 Welcome screen with real sessions** — query session index. 1 hr.
