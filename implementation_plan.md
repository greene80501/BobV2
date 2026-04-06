# Bob V2 — Implementation Plan
**Sections 2, 3 & 4: Tools, Multi-Agent, Slash Commands**  
_Generated: 2026-04-06_

---

## Architecture Contract

Every new feature must follow these rules:

**Model Tools**: A module in `bob/tools/` that exports a handler, description, and JSON schema. Registration happens in `bob/core/session.py` inside `_register_builtin_tools()`. The `ToolContext` object exposes `.cwd`, `.sandbox`, `.cancel_event`, `.on_output_delta`, `.on_plan_update`, `.on_request_user_input`, and `.thread_manager`.

**Slash Commands**: Enum values in `bob/tui/slash_commands.py`. Dispatched in `bob/tui/interface.py` inside `_dispatch_slash()`. The `else` fallback at the end prints "not yet implemented".

**Events**: All event types live in `bob/protocol/events.py`. Prefer reusing `InfoEvent` for subagent output rather than adding new event types (which require changes in 4+ files).

**Multi-Agent**: The stubs in `bob/tools/multi_agent/` all delegate to `context.thread_manager`, which is currently `None` in `ToolContext.__init__` in `session.py`. A `ThreadManager` must be created and injected.

---

## Key Architectural Decisions (read before implementing)

1. **Tool handlers are pure Python, not shell wrappers.** This gives better error messages, cross-platform behavior, and cancellation support.

2. **Multi-agent uses in-process `BobSession` instances, not subprocesses.** In-process sessions share the asyncio event loop, making `wait_for_agent` a simple `await done_event.wait()`.

3. **Subagent output surfaces via `InfoEvent`, not custom events.** Zero-protocol-change path, still renders correctly in the TUI.

4. **`/commit` uses a `_quick_model_turn()` helper.** Submits a real model turn within a slash command handler. Set `self._task_running = True` before and restore on completion.

5. **Plan mode uses tool filtering at spec-generation time.** When `session._plan_mode = True`, the `get_tool_specs()` call in `turn.py` returns only read-only tools. Cleaner than rejecting at dispatch.

---

## Phase 1 — Days 1–2: File Tools + Easy Slash Commands

### New Tools

#### 1.1 `read_file` — `bob/tools/read_file.py` (~60 lines)
- Use `pathlib.Path.read_text(encoding="utf-8", errors="replace")`
- Cap at 10,000 lines with truncation note
- Support optional `start_line`/`end_line` slice (1-indexed, inclusive)
- Schema: `path` (required), `start_line` (opt int), `end_line` (opt int), `encoding` (opt, default `"utf-8"`)
- Context used: `context.cwd` only
- No blockers

#### 1.2 `write_file` — `bob/tools/write_file.py` (~40 lines)
- `path.parent.mkdir(parents=True, exist_ok=True)` then `path.write_text(content)`
- Return confirmation string with byte count
- Schema: `path` (required), `content` (required), `encoding` (opt, default `"utf-8"`)
- Context used: `context.cwd`
- No blockers

#### 1.3 `edit_file` — `bob/tools/edit_file.py` (~70 lines)
- Exact string replacement: read file, assert `old_string` appears exactly once, replace with `new_string`, write back
- Error if zero matches; warn if multiple
- `create` mode: empty `old_string` + file doesn't exist → write the file
- Schema: `path` (required), `old_string` (required), `new_string` (required)
- Context used: `context.cwd`
- No blockers

#### 1.4 `glob_files` — `bob/tools/glob_files.py` (~50 lines)
- Use `pathlib.Path.glob()` relative to `cwd`
- Return newline-delimited list of matching paths, cap at 1,000 results
- Schema: `pattern` (required), `path` (opt string for root override)
- Context used: `context.cwd`
- No blockers

#### 1.5 `grep_files` — `bob/tools/grep_files.py` (~90 lines)
- Walk file tree, open each file, find lines matching regex
- Return `filepath:lineno:line` format, cap total output at 500 lines
- Schema: `pattern` (required, regex), `path` (opt search root), `file_pattern` (opt glob filter e.g. `"*.py"`), `case_insensitive` (opt bool), `max_results` (opt int, default 200)
- Context used: `context.cwd`
- No extra dependencies (pure stdlib `re` + `pathlib`)

#### 1.6 Register all Phase 1 tools
- **File**: `bob/core/session.py` → `_register_builtin_tools()`
- Add import + register block for each tool after the `list_dir` registration
- ~30 lines added

---

### New Slash Commands (Phase 1)

**File**: `bob/tui/slash_commands.py` — add to `SlashCommand` enum + `COMMAND_DESCRIPTIONS`  
**File**: `bob/tui/interface.py` — add `elif` blocks in `_dispatch_slash()`

#### 1.7 `/help`
- Add `HELP = "help"` to enum
- Render `COMMAND_DESCRIPTIONS` as a grouped two-column table via `_p()` calls
- Groups: Navigation, Session, Tools, Config, Agent
- ~25 lines in `_dispatch_slash`

#### 1.8 `/model <name>`
- Add `MODEL = "model"` (already in enum — just needs dispatch wiring)
- If `args.strip()` is non-empty: update `self._config.model = args.strip()`; submit `OverrideTurnContextOp(model=args.strip())` which already exists in `ops.py`
- If no args: display current model
- ~15 lines

#### 1.9 `/effort <low|medium|high>`
- Add `EFFORT = "effort"` to enum (already exists — wire dispatch)
- Map `low/medium/high` strings to `ReasoningEffort` enum values
- Store on `self._config.reasoning_effort`
- ~20 lines

#### 1.10 `/cost` and token tracking
- Add `COST = "cost"` to enum
- In `Interface.__init__`: add `self._total_input_tokens = 0`, `self._total_output_tokens = 0`, `self._estimated_cost_usd = 0.0`
- In `_consume_events` at the `TurnEndedEvent` handler: increment totals from `msg.input_tokens` + `msg.output_tokens`; compute cost using a model-rate dict (hardcode rates per 1k tokens for known models)
- `/cost` dispatch: display formatted totals
- ~30 lines total across both locations

#### 1.11 `/usage`
- Add `USAGE = "usage"` to enum
- Store `self._last_turn_tokens: dict = {}` in `__init__`, update in `_consume_events` on `TurnEndedEvent`
- `/usage` dispatch: display per-turn token breakdown
- ~20 lines

---

### Phase 1 File Summary

| Action | File | Lines |
|--------|------|-------|
| CREATE | `bob/tools/read_file.py` | ~60 |
| CREATE | `bob/tools/write_file.py` | ~40 |
| CREATE | `bob/tools/edit_file.py` | ~70 |
| CREATE | `bob/tools/glob_files.py` | ~50 |
| CREATE | `bob/tools/grep_files.py` | ~90 |
| MODIFY | `bob/core/session.py` | +30 |
| MODIFY | `bob/tui/slash_commands.py` | +12 |
| MODIFY | `bob/tui/interface.py` | +80 |

---

## Phase 2 — Days 3–5: Web, Ask User, Plan Mode, Todo, Sleep

### New Tools

#### 2.1 `web_fetch` — `bob/tools/web_fetch.py` (~80 lines)
- `httpx` async to fetch URL; `html2text` to convert HTML → Markdown
- Truncate at 50,000 characters with note
- Return raw text for non-HTML content types
- Schema: `url` (required), `max_length` (opt int, default 50000), `start_index` (opt int for pagination)
- **Blocker**: `httpx` and `html2text` must be in `pyproject.toml` / installed
- Register in `session.py` `_register_builtin_tools()`

#### 2.2 `web_search` — `bob/tools/web_search.py` (~70 lines)
- Use `duckduckgo_search` pip package (no API key needed) for MVP
- Return top N results as Markdown (title + URL + snippet)
- Only activate when `config.web_search_mode != DISABLED`
- Schema: `query` (required), `max_results` (opt int, default 5)
- Emit `WebSearchStartedEvent` / `WebSearchCompletedEvent` (already defined in `events.py`)
- **Modification to `ToolContext`**: Add `self.emit = None` in `ToolContext.__init__` in `session.py`; set it per-turn in `run_turn`
- **Blocker**: `duckduckgo_search` must be installed

#### 2.3 `ask_user` — wire up existing `request_user_input.py`
- The tool exists; the callback `context.on_request_user_input` is currently `None`
- **Modify `bob/core/session.py`**:
  - Add `self._pending_user_inputs: dict[str, asyncio.Future] = {}` to `__init__`
  - Add handling of `UserInputAnswerOp` in `_agent_loop` (mirror the `ExecApprovalOp` pattern)
  - Add `async def request_user_input(self, request_id, prompt, fields) -> str` method
- **Modify `bob/core/turn.py`**: In "Attach per-turn callbacks" section, add `ctx.on_request_user_input = session.request_user_input`
- **Modify `bob/tui/interface.py`**: Add handler for `UserInputRequestEvent` in `_consume_events` — stop spinner, print prompt, read user input via `ps.prompt_async()`, submit `UserInputAnswerOp`
- ~50 lines across three files

#### 2.4 `sleep` — `bob/tools/sleep_tool.py` (~25 lines)
- `await asyncio.sleep(seconds)` with periodic checks of `cancel_event`
- Cap at 300 seconds
- Schema: `seconds` (required number, 0–300)
- Context used: `context.cancel_event`
- No blockers

#### 2.5 `todo_write` — `bob/tools/todo_write.py` (~60 lines)
- Manage `.bob-todos.json` in workspace root
- Read on each call, merge in new items, write back
- Schema: `todos` (required array of `{id, content, status, priority}`)
- `status` values: `pending`, `in_progress`, `done`
- Context used: `context.cwd`
- No blockers

#### 2.6 `enter_plan_mode` / `exit_plan_mode` — `bob/tools/plan_mode.py` (~40 lines)
- Two tools: `enter_plan_mode` and `exit_plan_mode`, both take no inputs
- **Modify `bob/core/session.py`**: Add `self._plan_mode: bool = False`
- **Modify `bob/core/turn.py`**: When calling `session.tool_registry.get_tool_specs()`, filter out write tools (`write_file`, `edit_file`, `shell`, `apply_patch`) when `session._plan_mode == True`
- Register both in `_register_builtin_tools()`

---

### Phase 2 File Summary

| Action | File | Lines |
|--------|------|-------|
| CREATE | `bob/tools/web_fetch.py` | ~80 |
| CREATE | `bob/tools/web_search.py` | ~70 |
| CREATE | `bob/tools/sleep_tool.py` | ~25 |
| CREATE | `bob/tools/todo_write.py` | ~60 |
| CREATE | `bob/tools/plan_mode.py` | ~40 |
| MODIFY | `bob/core/session.py` | +50 |
| MODIFY | `bob/core/turn.py` | +20 |
| MODIFY | `bob/tui/interface.py` | +30 |

---

## Phase 3 — Week 2: Medium Slash Commands

All changes go into `bob/tui/interface.py` and `bob/tui/slash_commands.py`.

### Required Helper First

#### 3.0 `_quick_model_turn(prompt: str) -> str` — add to `Interface` (~40 lines)
- Submits `UserTurnOp`, sets `self._task_running = True`
- Waits for `TurnEndedEvent` by draining the event queue
- Returns accumulated `TextFinalEvent` text
- Used by `/commit`, `/summary`, `/review`
- **Add to `bob/tui/interface.py`** before `_dispatch_slash`

### Commands

#### 3.1 `/commit` (~60 lines)
1. Run `git status --short` and `git diff --cached` (subprocess)
2. If nothing staged: confirm with user then run `git add -A`
3. Call `_quick_model_turn(f"Write a concise git commit message for this diff:\n{diff}")` 
4. Run `git commit -m "<response>"`
- Add `COMMIT = "commit"` to `SlashCommand` (already in enum — wire dispatch)

#### 3.2 `/branch <name>` (~15 lines)
- Run `git checkout -b <name>` as subprocess, print result
- Add `BRANCH = "branch"` to enum (already exists — wire dispatch)

#### 3.3 `/export [file]` (~50 lines)
- Walk `session.context_manager.raw_items()` (already exists in `context_manager.py`)
- Format user/assistant turns as Markdown
- Write to `args.strip()` if given, else `~/bob-export-<timestamp>.md`
- Add `EXPORT = "export"` to enum

#### 3.4 `/rewind [N]` (~15 lines)
- `UndoOp(turns=N)` already exists in `ops.py` and is handled in `session.py`
- Parse int arg, call `await self._session.submit(UndoOp(turns=n))`
- Add `REWIND = "rewind"` to enum

#### 3.5 `/summary` (~20 lines)
- Call `_quick_model_turn("Summarize what has been accomplished in this session so far")`
- Depends on 3.0 being done first
- Add `SUMMARY = "summary"` to enum (already exists — wire dispatch)

#### 3.6 `/doctor` (~60 lines)
Checks to run:
1. `OPENAI_API_KEY` env var set?
2. HTTP connectivity to `config.base_url` (quick `HEAD` via `httpx`)
3. `BobConfig.model_validate(config.model_dump())` — config valid?
4. Each MCP server in `config.mcp_servers` — command exists in PATH?
5. Print `✓`/`✗` color-coded for each check
- Add `DOCTOR = "doctor"` to enum

#### 3.7 `/context <url|file>` (~50 lines)
- If arg starts with `http://` or `https://`: use `web_fetch` logic to fetch + convert to Markdown
- If arg is a file path: read with `pathlib`
- Store in `self._pending_context_items: list[str] = []` (add to `__init__`)
- In `run()` loop where `UserTurnOp` is built: prepend items to user message text, then clear list
- Add `CONTEXT = "context"` to enum

#### 3.8 `/output-style <brief|normal|verbose>` (~30 lines)
- Store `self._output_style: str = "normal"` in `__init__`
- Inject a style directive into the next `UserTurnOp` system message
- Add `OUTPUT_STYLE = "output-style"` to enum (already exists — wire dispatch)

---

### Phase 3 File Summary

| Action | File | Lines |
|--------|------|-------|
| MODIFY | `bob/tui/slash_commands.py` | +16 |
| MODIFY | `bob/tui/interface.py` | +290 total |

---

## Phase 4 — Week 3: Multi-Agent System

### 4.1 `ThreadManager` — `bob/core/thread_manager.py` (~200 lines)

**Architecture**:
```python
@dataclass
class AgentRecord:
    id: str
    session: BobSession
    task: str
    status: str          # pending | running | completed | failed
    result: Optional[str]
    color: str           # ANSI escape for this agent's output
    task_ref: Optional[asyncio.Task]
    done_event: asyncio.Event

class ThreadManager:
    parent_session: BobSession
    _agents: dict[str, AgentRecord]
    _color_palette: list[str]    # 8 ANSI colors, assigned round-robin
```

**Color palette** (8 entries, round-robin assignment):
```
\033[36m  cyan
\033[32m  green
\033[33m  yellow
\033[35m  magenta
\033[34m  blue
\033[31m  red
\033[37m  white
\033[96m  bright cyan
```

**Key methods**:

`async spawn(task, model=None, cwd=None, template=None) -> str`
1. Copy `parent_session.config`; override model if given
2. Instantiate `BobSession(config, cwd or parent.cwd)`
3. Assign `AgentRecord` with new `uuid4()` id + next color
4. `await agent_record.session.start()`
5. Create asyncio Task calling `_agent_worker(agent_id, task)`
6. Return `agent_id`

`async _agent_worker(agent_id, task)`
1. Submit `UserTurnOp(items=[TextUserInput(text=task)])` to subagent session
2. Drain events until `TurnEndedEvent` or `SessionEndedEvent`
3. Forward each event to parent via `InfoEvent(message=f"[{color}{agent_id}\033[0m] {text}")`
4. Collect final text as `agent_record.result`
5. Set `agent_record.status = "completed"`, signal `done_event`

`async send_message(agent_id, message)` — submit new `UserTurnOp` to subagent

`async wait_for_agent(agent_id, timeout=None) -> Optional[str]` — `await asyncio.wait_for(done_event.wait(), timeout=timeout)`

`async close_agent(agent_id, reason="")` — cancel task, `await session.shutdown()`

`list_agents(include_completed=False) -> list` — return descriptors from `_agents`

---

### 4.2 Wire `ThreadManager` into `ToolContext`

**Modify `bob/core/session.py`**:
- Add `self._thread_manager: Optional[ThreadManager] = None` to `__init__`
- Add method `def ensure_thread_manager(self) -> ThreadManager:` — lazily creates and caches

**Modify `bob/core/turn.py`** — in "Attach per-turn callbacks" section:
```python
ctx.thread_manager = session.ensure_thread_manager()
```
~5 lines added

---

### 4.3 Register multi-agent tools

**Modify `bob/core/session.py`** → `_register_builtin_tools()`:
- Add imports and registration blocks for all 5 stubs in `bob/tools/multi_agent/`
- `spawn_agent`, `send_message`, `wait_agent`, `list_agents`, `close_agent`
- ~25 lines added

---

### 4.4 TUI: Subagent output rendering

No changes needed in `interface.py`. `ThreadManager._agent_worker` emits forwarded events as `InfoEvent(message=f"[{color}{short_id}\033[0m] {text}")`, which the existing `InfoEvent` handler at line 574 renders as `_d(msg.message)`. The color codes inside the message string pass through.

---

### 4.5 Built-in agent templates — `bob/core/agent_templates.py` (~80 lines)

```python
@dataclass
class AgentTemplate:
    system_prompt_suffix: str
    allowed_tools: set[str]  # if empty, allow all

AGENT_TEMPLATES = {
    "explore": AgentTemplate(
        system_prompt_suffix="You are a fast filesystem exploration agent...",
        allowed_tools={"shell", "list_dir", "glob_files", "grep_files", "read_file"},
    ),
    "plan": AgentTemplate(
        system_prompt_suffix="You are a planning agent. Do not write or modify files...",
        allowed_tools={"read_file", "glob_files", "grep_files", "list_dir", "update_plan"},
    ),
    "verify": AgentTemplate(
        system_prompt_suffix="You are a verification agent. Run tests and check correctness...",
        allowed_tools={"shell", "read_file", "glob_files", "grep_files"},
    ),
}
```

Add `template` field to `spawn_agent` schema. In `spawn_agent_handler`, look up the template and pass it to `ThreadManager.spawn()`. The thread manager applies the suffix and filters tool specs for the subagent.

**Modify `bob/tools/multi_agent/spawn_agent.py`**: Add `template` field support (+20 lines)

---

### 4.6 `/review` slash command (~30 lines)

`SlashCommand.REVIEW` already exists in the enum. Wire dispatch:
1. Get last git diff (`git diff HEAD --stat`)
2. Spawn a `verify` template agent with the diff as task context
3. Print a message with the agent ID and color

**Modify `bob/tui/interface.py`** — add `elif cmd == SlashCommand.REVIEW:` in `_dispatch_slash`

---

### Phase 4 File Summary

| Action | File | Lines |
|--------|------|-------|
| CREATE | `bob/core/thread_manager.py` | ~200 |
| CREATE | `bob/core/agent_templates.py` | ~80 |
| MODIFY | `bob/core/session.py` | +45 |
| MODIFY | `bob/core/turn.py` | +5 |
| MODIFY | `bob/tools/multi_agent/spawn_agent.py` | +20 |
| MODIFY | `bob/tui/interface.py` | +30 |

---

## Phase 5 — Week 4+: Complex Features

### 5.1 `js_repl` — `bob/tools/js_repl.py` (~60 lines)
- `asyncio.create_subprocess_exec("node", "--input-type=module", stdin=PIPE, stdout=PIPE, stderr=PIPE)`
- Pipe `code` to stdin, cap execution at 10 seconds, use `cancel_event`
- Return stdout + stderr
- Schema: `code` (required), `timeout` (opt int ms, default 10000)
- **Blocker**: Node.js must be in PATH — check and return clear error if missing

### 5.2 `notebook_read` — `bob/tools/notebook_read.py` (~80 lines)
- `.ipynb` files are JSON — use `json.loads(path.read_text())`
- Format each cell: `[Cell N - code/markdown]` + source + truncated outputs
- Schema: `path` (required), `include_outputs` (opt bool, default True)
- No extra dependencies (pure stdlib)

### 5.3 `notebook_edit` — `bob/tools/notebook_edit.py` (~70 lines)
- Read `.ipynb` JSON, locate cell by index, replace source, optionally clear outputs, write back
- Schema: `path` (required), `cell_index` (required int), `new_source` (required), `clear_outputs` (opt bool, default False)
- No extra dependencies

### 5.4 `/vi` — vi input mode (~20 lines)
- Add `self._vi_mode: bool = False` to `Interface.__init__`
- Add `VI = "vi"` to `SlashCommand`
- Toggle flag in dispatch. At top of `run()` loop, recreate `PromptSession(vi_mode=self._vi_mode, ...)` when flag changes
- `prompt_toolkit` supports vi mode natively — no extra deps

### 5.5 `/theme <dark|light|no-color>` (~60 lines)
- Refactor module-level color helpers (`_d`, `_r`, `_g`, etc.) into methods on `Interface` or a `_Theme` dataclass that the helpers delegate to
- `dark` = current ANSI colors; `light` = inverted dim/bright; `no-color` = all helpers return input unchanged
- `THEME = "theme"` already in `SlashCommand` enum — wire dispatch
- **Note**: This is the only change with internal refactor risk. Do it in a separate branch.

### 5.6 `/hooks` slash command (~30 lines)
- Add `HOOKS = "hooks"` to `SlashCommand` enum
- List `self._config.hooks` with name, event, command, timeout
- Wire dispatch in `_dispatch_slash`

---

### Phase 5 File Summary

| Action | File | Lines |
|--------|------|-------|
| CREATE | `bob/tools/js_repl.py` | ~60 |
| CREATE | `bob/tools/notebook_read.py` | ~80 |
| CREATE | `bob/tools/notebook_edit.py` | ~70 |
| MODIFY | `bob/tui/interface.py` | +60 |
| MODIFY | `bob/tui/slash_commands.py` | +4 |

---

## Dependency Order (Critical Path)

```
Phase 1 (no deps)
  └── 1.6 Register tools → depends on 1.1–1.5 existing
  └── 1.10 /cost tracking → depends on TurnEndedEvent having token fields (it does)

Phase 2
  └── 2.1 web_fetch → httpx + html2text must be installed
  └── 2.3 ask_user → requires ToolContext.emit + session._pending_user_inputs
  └── 2.6 plan_mode → requires session._plan_mode + turn.py filter

Phase 3
  └── 3.0 _quick_model_turn() → MUST be done before 3.1, 3.5, 4.6
  └── 3.7 /context → web_fetch (2.1) must exist for URL fetching

Phase 4
  └── 4.1 ThreadManager → MUST be done before 4.2, 4.3
  └── 4.2 Wire ToolContext → depends on 4.1
  └── 4.3 Register tools → depends on 4.2
  └── 4.5 Agent templates → depends on 4.1
  └── 4.6 /review → depends on 3.0 + 4.5

Phase 5 (independent of phases 1–4 except vi/theme are pure TUI)
```

---

## Total Effort Estimate

| Phase | New Files | Modified Files | Total New Lines | Est. Time |
|-------|-----------|----------------|-----------------|-----------|
| 1 | 5 | 3 | ~370 | Day 1–2 |
| 2 | 5 | 3 | ~305 | Day 3–5 |
| 3 | 0 | 2 | ~306 | Week 2 |
| 4 | 2 | 4 | ~380 | Week 3 |
| 5 | 3 | 2 | ~274 | Week 4+ |
| **Total** | **15** | **14** | **~1,635** | **~4 weeks** |

---

## Critical Files for Implementation (Reference Often)

| File | Why Critical |
|------|-------------|
| `bob/core/session.py` | Tool registration, ToolContext, session lifecycle |
| `bob/core/turn.py` | Tool call dispatch, parallel execution, callbacks |
| `bob/tui/interface.py` | All slash command dispatch, event rendering, UI |
| `bob/tui/slash_commands.py` | SlashCommand enum, descriptions |
| `bob/tools/multi_agent/spawn_agent.py` | Template-based agent spawning |
| `bob/protocol/ops.py` | All operations (UndoOp, OverrideTurnContextOp, etc.) |
| `bob/protocol/events.py` | All event types (UserInputRequestEvent, etc.) |
