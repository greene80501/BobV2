# BOB — Your AI-Powered Development Partner
### Complete Implementation Plan — Exact Codex Parity in Python

---

## Overview

Bob is a **pixel-perfect Python rewrite of OpenAI Codex CLI** with exactly two modifications:
1. Written in **Python 3.11+** instead of Rust
2. Named **`bob`** instead of `codex`

Everything else — every tool, every slash command, every event, every TUI widget, every protocol type, every behavior — is an exact copy. The model is `gpt-5.1-codex-mini` via the OpenAI SDK using the **Responses API** (the same API Codex uses).

---

## Tech Stack

| Concern | Choice | Replaces (Codex Rust) |
|---|---|---|
| Language | Python 3.11+ | Rust 2024 edition |
| LLM | `openai` SDK, `gpt-5.1-codex-mini`, Responses API | OpenAI Responses API |
| TUI | `textual` | Ratatui + crossterm |
| CLI | `typer` | clap |
| Async runtime | `asyncio` | Tokio |
| Config parsing | `tomllib` (stdlib) | TOML crate |
| Data models | `pydantic` v2 | serde / serde_json |
| SQLite | `aiosqlite` | rusqlite / sqlx |
| File I/O | `aiofiles` | Tokio fs |
| MCP | `mcp` Python SDK | rmcp crate |
| Subprocess | `asyncio.create_subprocess_exec` | Tokio process |
| Fuzzy match | `rapidfuzz` | codex-utils-fuzzy-match |

---

## Entry Points (CLI)

```
bob                              # Interactive TUI (primary entry point)
bob "initial prompt"             # TUI with initial message pre-sent
bob --resume SESSION_ID          # Resume session into TUI
bob --model gpt-5.1-codex-mini   # Override model at launch
bob --sandbox workspace-write    # Override sandbox mode
bob --approval on-request        # Override approval policy
bob -C /path/to/dir              # Override working directory

bob exec PROMPT                  # Headless non-interactive mode
bob exec --resume SESSION_ID     # Headless resume
bob exec --resume --last         # Headless resume most recent session
bob exec --json PROMPT           # Headless with JSONL output
bob exec --ephemeral PROMPT      # No session persistence
bob exec --full-auto PROMPT      # workspace-write + on-request auto
bob exec --yolo PROMPT           # danger-full-access + never (DANGEROUS)
bob exec -i image.png PROMPT     # Attach image(s) to prompt
bob exec -o out.txt PROMPT       # Write last message to file
bob exec --output-schema s.json  # Constrain final output to JSON schema

bob app-server                   # JSON-RPC 2.0 server (WebSocket)
bob app-server --stdio           # JSON-RPC 2.0 server (stdin/stdout, VS Code default)

bob mcp add NAME CMD [ARGS...]   # Add MCP server to config
bob mcp list                     # List configured MCP servers
bob mcp remove NAME              # Remove MCP server

bob completion bash               # Print bash completion script
bob completion zsh                # Print zsh completion script
```

---

## TUI UX — Exact Codex Behavior

**`bob` launches directly into the interactive chat.** No subcommand needed.

Inside the TUI:
- **Plain text** → sends to model (streaming response)
- **`/command`** → executes slash command (fuzzy autocomplete popup opens instantly)
- **`!command`** → runs a shell command directly via `Op::RunUserShellCommand`

### Keyboard Shortcuts

| Key | Action |
|---|---|
| `Enter` | Submit message |
| `Shift+Enter` | Newline in composer |
| `Ctrl+C` / `Ctrl+G` | Interrupt current turn |
| `Ctrl+D` | Quit |
| `PgUp` / `PgDn` | Scroll chat history |
| `Ctrl+T` | Toggle transcript overlay |
| `Ctrl+L` | Clear (same as `/clear`) |
| `Tab` | Autocomplete slash command |
| `Esc` | Dismiss popup / cancel |
| `Up` arrow (in composer) | Previous message in history |

---

## All Slash Commands (Exact Codex List)

Typed as `/command` in composer. Popup appears on `/`. Ordered by frequency (matches Codex `SlashCommand` enum order exactly).

| Command | Description | Available During Task? | Args |
|---|---|---|---|
| `/model` | Choose model and reasoning effort | No | |
| `/fast` | Toggle Fast mode (2X plan usage) | No | optional: on/off |
| `/approvals` | Choose what bob is allowed to do | No | |
| `/permissions` | Choose what bob is allowed to do (alias) | No | |
| `/setup-default-sandbox` | Set up elevated agent sandbox | No | |
| `/sandbox-add-read-dir` | Let sandbox read a directory | No | `<absolute_path>` |
| `/experimental` | Toggle experimental features | No | |
| `/skills` | Use skills to improve how bob performs tasks | Yes | |
| `/review` | Review current changes and find issues | No | optional: args |
| `/rename` | Rename the current thread | Yes | `<name>` |
| `/new` | Start a new chat during a conversation | No | |
| `/resume` | Resume a saved chat | No | |
| `/fork` | Fork the current chat | No | |
| `/init` | Create an AGENTS.md file | No | |
| `/compact` | Summarize conversation to prevent hitting context limit | No | |
| `/plan` | Switch to Plan mode | No | optional: description |
| `/collab` | Change collaboration mode | Yes | |
| `/agent` | Switch the active agent thread | Yes | |
| `/diff` | Show git diff (including untracked files) | Yes | |
| `/copy` | Copy latest bob output to clipboard | Yes | |
| `/mention` | Mention a file (attach to next message) | Yes | |
| `/status` | Show current session configuration and token usage | Yes | |
| `/debug-config` | Show config layers and requirement sources | Yes | |
| `/title` | Configure terminal title items | No | |
| `/statusline` | Configure status line items | No | |
| `/theme` | Choose syntax highlighting theme | No | |
| `/mcp` | List configured MCP tools | Yes | |
| `/apps` | Manage apps / connectors | Yes | |
| `/plugins` | Browse plugins | Yes | |
| `/logout` | Log out of bob | No | |
| `/quit` / `/exit` | Exit bob | Yes | |
| `/feedback` | Send logs to maintainers | Yes | |
| `/rollout` | Print the rollout file path | Yes | (debug only) |
| `/ps` | List background terminals | Yes | |
| `/stop` / `/clean` | Stop all background terminals | Yes | |
| `/clear` | Clear terminal and start a new chat | No | |
| `/personality` | Choose a communication style | No | |
| `/realtime` | Toggle realtime voice mode (experimental) | Yes | |
| `/settings` | Configure realtime microphone/speaker | Yes | |
| `/subagents` | Switch the active agent thread (alias for `/agent`) | Yes | |
| `/debug-m-drop` | Drop all memories (debug) | No | |
| `/debug-m-update` | Update memories (debug) | No | |

Commands supporting inline args: `/review`, `/rename`, `/plan`, `/fast`, `/sandbox-add-read-dir`

---

## Project Structure

```
bob/
├── pyproject.toml
├── BOB_PLAN.md
├── AGENTS.md
│
└── bob/
    ├── __init__.py
    ├── __main__.py                        # python -m bob
    │
    ├── cli/
    │   ├── __init__.py
    │   ├── main.py                        # typer app — `bob` → TUI; subcommands
    │   └── exec_cmd.py                    # `bob exec` headless runner
    │
    ├── protocol/
    │   ├── __init__.py
    │   ├── ops.py                         # ALL Op variants (see full list below)
    │   ├── events.py                      # ALL EventMsg variants (see full list below)
    │   ├── config_types.py                # AskForApproval, SandboxPolicy, Personality, etc.
    │   ├── items.py                       # ResponseItem, UserInput, TurnItem, ContentItem
    │   ├── plan_types.py                  # UpdatePlanArgs, PlanItemArg, StepStatus
    │   └── review_types.py               # ReviewRequest, ReviewTarget, ReviewFinding
    │
    ├── config/
    │   ├── __init__.py
    │   ├── schema.py                      # BobConfig full Pydantic model
    │   └── loader.py                      # 4-layer TOML merge (defaults→user→project→CLI)
    │
    ├── core/
    │   ├── __init__.py
    │   ├── session.py                     # BobSession: sq + eq + agent loop
    │   ├── codex_thread.py                # CodexThread: wraps session per thread
    │   ├── thread_manager.py              # ThreadManager: all active threads + lifecycle
    │   ├── turn.py                        # Single turn: prompt → stream → tools → repeat
    │   ├── context_manager.py             # History list + token counting + truncation
    │   ├── compact.py                     # Compaction algorithm (summarize → replace history)
    │   ├── rollout_reconstruction.py      # Resume/fork history rebuild from JSONL
    │   ├── exec.py                        # execute_command() with streaming + sandbox + cap
    │   ├── exec_policy.py                 # Trusted commands, execpolicy evaluation
    │   ├── environment_context.py         # OS/cwd/shell/time environment injection
    │   └── agent/
    │       ├── __init__.py
    │       ├── control.py                 # AgentControl (cancel token, interrupt)
    │       └── review.py                  # Review mode handler
    │
    ├── client/
    │   ├── __init__.py
    │   └── openai_client.py               # AsyncOpenAI Responses API wrapper + streaming
    │
    ├── tools/
    │   ├── __init__.py
    │   ├── registry.py                    # ToolRegistry: register, dispatch, get_specs
    │   ├── shell.py                       # shell / local_shell tool handler
    │   ├── apply_patch.py                 # apply_patch tool + custom format parser
    │   ├── apply_patch_instructions.md    # Injected into system prompt
    │   ├── update_plan.py                 # update_plan tool handler
    │   ├── web_search.py                  # web_search tool handler
    │   ├── view_image.py                  # view_image tool handler
    │   ├── list_dir.py                    # list_dir tool handler (experimental)
    │   ├── request_user_input.py          # request_user_input tool handler
    │   ├── request_permissions.py         # request_permissions tool handler
    │   └── multi_agent/
    │       ├── __init__.py
    │       ├── spawn_agent.py             # spawn_agent tool (v2)
    │       ├── send_message.py            # send_message tool (v2)
    │       ├── assign_task.py             # assign_task tool (v2)
    │       ├── wait_agent.py              # wait_agent tool (v2)
    │       ├── close_agent.py             # close_agent tool (v2)
    │       └── list_agents.py             # list_agents tool (v2)
    │
    ├── sandbox/
    │   ├── __init__.py                    # get_sandbox_runner(policy) → SandboxRunner
    │   ├── base.py                        # SandboxRunner ABC
    │   ├── macos.py                       # SeatbeltSandbox (sandbox-exec)
    │   ├── linux.py                       # BubblewrapSandbox (bwrap) + Landlock fallback
    │   └── windows.py                     # RestrictedTokenSandbox (pywin32) / noop
    │
    ├── rollout/
    │   ├── __init__.py
    │   ├── recorder.py                    # Async JSONL writer
    │   ├── state_db.py                    # aiosqlite: threads table + migrations
    │   └── session_index.py               # Thread name→ID→path index
    │
    ├── mcp/
    │   ├── __init__.py
    │   ├── client.py                      # McpServerConnection: subprocess + mcp SDK
    │   ├── manager.py                     # McpManager: lifecycle + reconnect
    │   └── server.py                      # Bob-as-MCP-server (stdio)
    │
    ├── memories/
    │   ├── __init__.py
    │   ├── storage.py                     # SQLite + markdown file memory store
    │   ├── phase1.py                      # Extraction: rollout → raw_memories.md
    │   └── phase2.py                      # Consolidation: raw → summary
    │
    ├── skills/
    │   ├── __init__.py
    │   ├── manager.py                     # SkillsManager: discover + cache
    │   └── watcher.py                     # SkillsWatcher: fs watch for changes
    │
    ├── plugins/
    │   ├── __init__.py
    │   └── manager.py                     # PluginsManager: install/list/uninstall
    │
    ├── hooks/
    │   ├── __init__.py
    │   └── runner.py                      # Hook execution (pre/post tool-use, session-start)
    │
    ├── instructions/
    │   ├── __init__.py
    │   └── loader.py                      # AGENTS.md walk-up + scoping rules
    │
    ├── prompts/
    │   └── system.md                      # Base system prompt (bob's guidelines)
    │
    ├── app_server/
    │   ├── __init__.py
    │   ├── server.py                      # JSON-RPC 2.0 WebSocket + stdio transport
    │   ├── protocol_v2.py                 # All v2 request/response types (Pydantic)
    │   └── message_processor.py           # Route JSON-RPC methods → ThreadManager ops
    │
    └── tui/
        ├── __init__.py
        ├── app.py                         # BobApp(textual.App) — main application
        ├── chat_widget.py                 # ChatWidget: history cells + active streaming cell
        ├── composer.py                    # ComposerWidget: input, slash detection, ! prefix
        ├── slash_commands.py              # SlashCommand enum + descriptions + fuzzy match
        ├── command_popup.py               # Autocomplete popup (appears on /)
        ├── approval_widget.py             # ExecApproval modal (y/n/a/d)
        ├── patch_approval_widget.py       # PatchApproval modal (diff display)
        ├── plan_widget.py                 # Plan checklist panel (update_plan rendering)
        ├── resume_picker.py               # Session picker (resume + fork, paginated 25/page)
        ├── model_picker.py                # Model picker (/model)
        ├── approval_picker.py             # Approval mode picker (/approvals)
        ├── sandbox_picker.py              # Sandbox mode picker (/permissions)
        ├── personality_picker.py          # Personality picker (/personality)
        ├── theme_picker.py                # Theme picker (/theme)
        ├── collab_picker.py               # Collaboration mode picker (/collab)
        ├── mcp_list_widget.py             # MCP tools display (/mcp)
        ├── status_widget.py               # Status display (/status)
        ├── elicitation_widget.py          # MCP elicitation request modal
        ├── user_input_widget.py           # request_user_input tool modal
        ├── markdown_render.py             # Markdown → Textual rich text
        ├── diff_render.py                 # Patch diff display with syntax highlight
        └── footer.py                      # Status bar: model | sandbox | approval | tokens
```

---

## Full Protocol Types

### ALL Ops (`bob/protocol/ops.py`)

Pydantic v2 discriminated union on `"type"` field:

```python
# Core turn ops
class UserTurnOp(BaseModel):
    type: Literal["user_turn"]
    items: list[UserInput]
    cwd: Path
    approval_policy: AskForApproval
    approvals_reviewer: Optional[ApprovalsReviewer] = None
    sandbox_policy: SandboxPolicy
    model: str
    effort: Optional[ReasoningEffortConfig] = None
    summary: Optional[ReasoningSummaryConfig] = None
    service_tier: Optional[Optional[ServiceTier]] = None
    final_output_json_schema: Optional[dict] = None
    collaboration_mode: Optional[CollaborationMode] = None
    personality: Optional[Personality] = None

class InterruptOp(BaseModel):
    type: Literal["interrupt"]

class CleanBackgroundTerminalsOp(BaseModel):
    type: Literal["clean_background_terminals"]

# Approvals
class ExecApprovalOp(BaseModel):
    type: Literal["exec_approval"]
    id: str
    turn_id: Optional[str] = None
    decision: ReviewDecision

class PatchApprovalOp(BaseModel):
    type: Literal["patch_approval"]
    id: str
    decision: ReviewDecision

class ResolveElicitationOp(BaseModel):
    type: Literal["resolve_elicitation"]
    server_name: str
    request_id: Union[str, int]
    decision: ElicitationAction
    content: Optional[dict] = None

class UserInputAnswerOp(BaseModel):
    type: Literal["user_input_answer"]
    id: str
    response: RequestUserInputResponse

class RequestPermissionsResponseOp(BaseModel):
    type: Literal["request_permissions_response"]
    id: str
    response: RequestPermissionsResponse

class DynamicToolResponseOp(BaseModel):
    type: Literal["dynamic_tool_response"]
    id: str
    response: DynamicToolResponse

# Context management
class OverrideTurnContextOp(BaseModel):
    type: Literal["override_turn_context"]
    cwd: Optional[Path] = None
    approval_policy: Optional[AskForApproval] = None
    approvals_reviewer: Optional[ApprovalsReviewer] = None
    sandbox_policy: Optional[SandboxPolicy] = None
    model: Optional[str] = None
    effort: Optional[ReasoningEffortConfig] = None
    summary: Optional[ReasoningSummaryConfig] = None
    service_tier: Optional[Optional[ServiceTier]] = None
    collaboration_mode: Optional[CollaborationMode] = None
    personality: Optional[Personality] = None

class CompactOp(BaseModel):
    type: Literal["compact"]

class AddToHistoryOp(BaseModel):
    type: Literal["add_to_history"]
    text: str

# Session control
class SetThreadNameOp(BaseModel):
    type: Literal["set_thread_name"]
    name: str

class UndoOp(BaseModel):
    type: Literal["undo"]

class ThreadRollbackOp(BaseModel):
    type: Literal["thread_rollback"]
    num_turns: int

class ShutdownOp(BaseModel):
    type: Literal["shutdown"]

# Review
class ReviewOp(BaseModel):
    type: Literal["review"]
    review_request: ReviewRequest

# Shell passthrough
class RunUserShellCommandOp(BaseModel):
    type: Literal["run_user_shell_command"]
    command: str  # raw string after '!'

# Queries
class ListModelsOp(BaseModel):
    type: Literal["list_models"]

class ListMcpToolsOp(BaseModel):
    type: Literal["list_mcp_tools"]

class RefreshMcpServersOp(BaseModel):
    type: Literal["refresh_mcp_servers"]
    config: dict  # mcp_servers + mcp_oauth_credentials_store_mode

class ReloadUserConfigOp(BaseModel):
    type: Literal["reload_user_config"]

class ListSkillsOp(BaseModel):
    type: Literal["list_skills"]
    cwds: list[Path] = []
    force_reload: bool = False

class GetHistoryEntryRequestOp(BaseModel):
    type: Literal["get_history_entry_request"]
    offset: int
    log_id: int

# Memory
class DropMemoriesOp(BaseModel):
    type: Literal["drop_memories"]

class UpdateMemoriesOp(BaseModel):
    type: Literal["update_memories"]

# Multi-agent
class InterAgentCommunicationOp(BaseModel):
    type: Literal["inter_agent_communication"]
    communication: InterAgentCommunication

# Realtime voice
class RealtimeConversationStartOp(BaseModel):
    type: Literal["realtime_conversation_start"]
    prompt: str
    session_id: Optional[str] = None

class RealtimeConversationAudioOp(BaseModel):
    type: Literal["realtime_conversation_audio"]
    frame: RealtimeAudioFrame

class RealtimeConversationTextOp(BaseModel):
    type: Literal["realtime_conversation_text"]
    text: str

class RealtimeConversationCloseOp(BaseModel):
    type: Literal["realtime_conversation_close"]
```

### ALL EventMsg Variants (`bob/protocol/events.py`)

```python
# Errors / warnings
ErrorEvent, WarningEvent

# Turn lifecycle
TurnStartedEvent       # turn_id, model_context_window, collaboration_mode_kind
TurnCompleteEvent      # turn_id
TurnAbortedEvent       # turn_id, reason
TokenCountEvent        # input_tokens, output_tokens, total_tokens (all Optional)

# Agent text output
AgentMessageEvent           # message, turn_id
AgentMessageDeltaEvent      # delta, turn_id
AgentReasoningEvent         # reasoning text
AgentReasoningDeltaEvent    # reasoning delta
AgentReasoningRawContentEvent       # raw chain-of-thought
AgentReasoningRawContentDeltaEvent  # raw delta
AgentReasoningSectionBreakEvent     # new reasoning section starts

# User message echo
UserMessageEvent      # echoes what was sent to model

# Plan
PlanUpdateEvent       # UpdatePlanArgs (steps list with statuses)
PlanDeltaEvent        # incremental plan delta

# Session
SessionConfiguredEvent     # session_id, thread_id, model, sandbox_policy, etc.
ThreadNameUpdatedEvent     # new_name
ModelRerouteEvent          # from_model, to_model

# Shell execution
ExecCommandBeginEvent      # call_id, process_id, turn_id, command, cwd, parsed_cmd, source
ExecCommandOutputDeltaEvent # call_id, data, stream (stdout|stderr)
ExecCommandEndEvent        # call_id, exit_code, duration, stdout, stderr, aggregated_output, status
TerminalInteractionEvent   # stdin_sent, stdout_observed

# Approvals
ExecApprovalRequestEvent         # call_id, turn_id, command, cwd, justification
ApplyPatchApprovalRequestEvent   # call_id, turn_id, changes (list of FileChange)
GuardianAssessmentEvent          # structured risk assessment for guardian approval flow
RequestPermissionsEvent          # id, permissions_requested
RequestUserInputEvent            # id, prompt, fields
DynamicToolCallRequest           # id, tool_name, input
DynamicToolCallResponseEvent     # id, result
ElicitationRequestEvent          # server_name, request_id, message, fields

# Patch
PatchApplyBeginEvent     # call_id, changes
PatchApplyEndEvent       # call_id, success, error

# MCP
McpStartupUpdateEvent     # server_name, status
McpStartupCompleteEvent   # summary of all server statuses
McpToolCallBeginEvent     # server_name, tool_name, call_id
McpToolCallEndEvent       # call_id, result_summary
McpListToolsResponseEvent # tools: list[McpToolSpec]

# Web search / image gen
WebSearchBeginEvent    # query, call_id
WebSearchEndEvent      # call_id, results_count
ImageGenerationBeginEvent  # prompt, call_id
ImageGenerationEndEvent    # call_id, image_path

# Skills
ListSkillsResponseEvent    # entries: list[SkillsListEntry]
SkillsUpdateAvailableEvent # signal to reload

# Memory
# (memory updates delivered via agent messages)

# Review mode
EnteredReviewModeEvent     # review_request
ExitedReviewModeEvent      # result: Optional[ReviewOutputEvent]

# Context
ContextCompactedEvent      # summary_preview
ThreadRolledBackEvent      # num_turns

# Multi-agent collab
CollabAgentSpawnBeginEvent, CollabAgentSpawnEndEvent
CollabAgentInteractionBeginEvent, CollabAgentInteractionEndEvent
CollabWaitingBeginEvent, CollabWaitingEndEvent
CollabCloseBeginEvent, CollabCloseEndEvent
CollabResumeBeginEvent, CollabResumeEndEvent

# Undo
UndoStartedEvent, UndoCompletedEvent

# Image viewing
ViewImageToolCallEvent    # image_path, call_id

# Hooks
HookStartedEvent    # hook_name, hook_type, scope
HookCompletedEvent  # hook_name, status

# History
GetHistoryEntryResponseEvent   # entry, offset, log_id

# Realtime voice
RealtimeConversationStartedEvent   # session_id, version
RealtimeConversationRealtimeEvent  # payload (various realtime sub-events)
RealtimeConversationClosedEvent    # reason

# Stream errors
StreamErrorEvent    # message, retry_count

# Misc
BackgroundEventEvent    # message (notifications from background tasks)
DeprecationNoticeEvent  # message
RawResponseItemEvent    # raw item (debug)
ItemStartedEvent, ItemCompletedEvent  # fine-grained item lifecycle
TurnDiffEvent           # diff summary for a turn
ShutdownCompleteEvent   # session shutting down
```

---

## All Tools (Exact Codex Parity)

### Always-Available Tools

| Tool name | Handler | Description | Parallel |
|---|---|---|---|
| `shell` / `local_shell` | ShellHandler | Execute shell commands in sandbox | Yes |
| `apply_patch` | ApplyPatchHandler | Apply custom patch format to files | No |
| `update_plan` | UpdatePlanHandler | Create/update task plan checklist in TUI | No |

### Feature-Gated Tools

| Tool | Condition | Description |
|---|---|---|
| `web_search` | `web_search_mode != Disabled` | Search the web |
| `view_image` | always | View local images (attach to context) |
| `list_dir` | experimental flag | List directory contents |
| `request_user_input` | `plan` collab mode or feature flag | Ask user a question |
| `request_permissions` | `request_permissions_tool` feature | Request runtime permission grants |
| `js_repl` / `js_repl_reset` | `js_repl_enabled` feature | Execute JavaScript in REPL |
| `image_generation` | `image_gen_tool` feature | Generate images |
| `list_mcp_resources` | MCP resources present | List MCP server resources |
| `read_mcp_resource` | MCP resources present | Read MCP resource |
| `tool_search` | `search_tool` + app_tools | Search available tools |
| `tool_suggest` | `tool_suggest` + discoverable tools | Suggest tools |

### Multi-Agent Tools (v2)

| Tool | Description |
|---|---|
| `spawn_agent` | Spawn a sub-agent with a task and config |
| `send_message` | Send message to another agent |
| `assign_task` | Assign a task to a sub-agent |
| `wait_agent` | Wait for sub-agent to complete |
| `close_agent` | Close a sub-agent thread |
| `list_agents` | List all active agent threads |

### MCP Tools
All tools from configured MCP servers are dynamically registered at startup with prefix `{server_name}__{tool_name}`.

---

## apply_patch Tool — Custom Format (Critical)

Claude is instructed to use `apply_patch` as a shell command. The patch is the second argument:

```
shell {"command": ["apply_patch", "*** Begin Patch\n*** Add File: hello.txt\n+Hello world\n*** End Patch\n"]}
```

### Grammar:
```
Patch   := "*** Begin Patch" NEWLINE { FileOp } "*** End Patch" NEWLINE
FileOp  := AddFile | DeleteFile | UpdateFile
AddFile := "*** Add File: " path NEWLINE { "+" line NEWLINE }
DeleteFile := "*** Delete File: " path NEWLINE
UpdateFile := "*** Update File: " path NEWLINE [ "*** Move to: " newpath NEWLINE ] { Hunk }
Hunk    := "@@" [ header ] NEWLINE { HunkLine } [ "*** End of File" NEWLINE ]
HunkLine := (" " | "+" | "-") text NEWLINE
```

### Rules:
- Context: 3 lines above and below each change
- Use `@@ class Foo` / `@@ def bar` for disambiguation if 3-line context is not unique
- Paths are ALWAYS relative, NEVER absolute
- New file lines must be prefixed with `+` even for `Add File`

### Python Implementation:
`bob/tools/apply_patch.py` — parse the custom format and apply to disk. Dispatched when shell command `argv[0] == "apply_patch"`.

The full instruction text is in `bob/tools/apply_patch_instructions.md` and injected into every system prompt.

---

## update_plan Tool

Called by the model (not the user) to track task progress. Renders a live checklist above the chat in the TUI.

```python
class StepStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"

class PlanItemArg(BaseModel):
    step: str
    status: StepStatus

class UpdatePlanArgs(BaseModel):
    explanation: Optional[str] = None
    plan: list[PlanItemArg]
```

The TUI's `PlanWidget` re-renders every time `PlanUpdateEvent` arrives. Only one `in_progress` step at a time.

---

## Config System

### File locations (lowest → highest priority):
1. Built-in defaults
2. `~/.bob/config.toml` — user config
3. `.bob/config.toml` — project config (walk up from cwd)
4. CLI flags (model, sandbox, approval, cwd)
5. `Op::OverrideTurnContext` — runtime session overrides

### Full BobConfig Schema (`bob/config/schema.py`):

```python
class BobConfig(BaseModel):
    model: str = "gpt-5.1-codex-mini"
    sandbox_mode: SandboxMode = SandboxMode.WORKSPACE_WRITE
    approval_policy: AskForApproval = AskForApproval.ON_REQUEST
    approvals_reviewer: ApprovalsReviewer = ApprovalsReviewer.USER
    personality: Personality = Personality.NONE
    collaboration_mode: Optional[CollaborationMode] = None
    
    # Paths
    bob_home: Path = Path.home() / ".bob"
    
    # Provider
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = "https://api.openai.com/v1"
    
    # Reasoning
    reasoning_effort: Optional[ReasoningEffort] = None
    reasoning_summary: Optional[ReasoningSummary] = None
    
    # Features
    web_search_mode: WebSearchMode = WebSearchMode.DISABLED
    web_search_config: Optional[WebSearchToolConfig] = None
    memories_enabled: bool = True
    js_repl_enabled: bool = False
    image_gen_tool: bool = False
    request_user_input: bool = False
    request_permissions_tool: bool = False
    multi_agent_v2: bool = True
    collab_tools: bool = False
    experimental: bool = False
    
    # Windows-specific
    windows_sandbox_level: WindowsSandboxLevel = WindowsSandboxLevel.LOOSE
    windows_sandbox_private_desktop: bool = False
    
    # MCP
    mcp_servers: dict[str, McpServerConfig] = {}
    
    # Notify
    notify_on_complete: Optional[str] = None  # script path
    
    # History
    history_enabled: bool = True
    
    # Service tier
    service_tier: Optional[ServiceTier] = None
```

### Key Config Types:

```python
class AskForApproval(str, Enum):
    UNLESS_TRUSTED = "untrusted"
    ON_FAILURE = "on-failure"
    ON_REQUEST = "on-request"
    NEVER = "never"
    # Granular variant: separate class with bool fields

class SandboxMode(str, Enum):
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    DANGER_FULL_ACCESS = "danger-full-access"

class ReviewDecision(str, Enum):
    APPROVED = "approved"
    APPROVED_FOR_SESSION = "approved_for_session"
    DENIED = "denied"
    ABORT = "abort"

class Personality(str, Enum):
    NONE = "none"
    FRIENDLY = "friendly"
    PRAGMATIC = "pragmatic"

class ReasoningEffort(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class WebSearchMode(str, Enum):
    DISABLED = "disabled"
    CACHED = "cached"
    LIVE = "live"

class ApprovalsReviewer(str, Enum):
    USER = "user"
    GUARDIAN_SUBAGENT = "guardian_subagent"

class CollaborationModeKind(str, Enum):
    DEFAULT = "default"
    PLAN = "plan"
    PAIR_PROGRAMMING = "pair_programming"
    EXECUTE = "execute"
```

---

## System Prompt Construction

Assembled per-session, updated as settings change. Composed of layers:

### 1. Base Instructions (`bob/prompts/system.md`)
```
You are a coding agent running in the bob CLI, Your AI-Powered Development Partner.
You are expected to be precise, safe, and helpful.

Your capabilities:
- Receive user prompts and other context provided by the harness
- Communicate by streaming responses and making/updating plans
- Emit function calls to run terminal commands and apply patches

[Personality guidelines — concise, direct, friendly by default]
[AGENTS.md spec — how to interpret project instruction files]
[Preamble message guidelines]
[Planning guidelines — when/how to use update_plan]
[Task execution guidelines]
[Shell command guidelines]
[apply_patch instructions — full custom format grammar]
[Final answer formatting guidelines]
```

### 2. Environment Context (injected per-turn, updated when changed)
```
OS: Windows 11 / macOS 14 / Ubuntu 22.04
CWD: /home/user/myproject
Shell: bash / zsh / powershell
Home: /home/user
Time: 2025-04-04T12:30:00Z
Git: main (3 uncommitted changes)
```

### 3. Permissions Context (injected when sandbox/approval changes)
```
Sandbox: workspace-write
  Writable: /home/user/myproject, /tmp
  Network: disabled
Approvals: on-request (will ask before running commands)
```

### 4. AGENTS.md content (concatenated, global→project priority)

### 5. Memory content (from `~/.bob/memories/raw_memories.md`, max 5000 tokens)

### 6. Collaboration mode instructions (injected when mode changes mid-session)

---

## Conversation History Format (OpenAI Responses API)

Bob uses the **Responses API**, not Chat Completions. The `input` field takes a flat list of items:

```python
# API call shape
response = await client.responses.create(
    model="gpt-5.1-codex-mini",
    instructions=system_prompt,   # separate from input
    input=history,                 # list of ResponseInputItem
    tools=tool_specs,
    stream=True,
)

# History item types:
# User message
{"role": "user", "content": [{"type": "input_text", "text": "..."}]}
# User message with image
{"role": "user", "content": [{"type": "input_image", "image_url": "..."}]}

# Assistant text + tool calls
{"role": "assistant", "content": [
    {"type": "output_text", "text": "..."},
    {"type": "tool_use", "id": "call_abc", "name": "shell", "input": {"command": ["ls"]}}
]}

# Tool result (immediately after the assistant message that called it)
{"role": "tool", "tool_call_id": "call_abc", "content": "file1.py\nfile2.py"}

# Developer instructions (environment context updates, injected inline)
{"role": "developer", "content": [{"type": "input_text", "text": "CWD changed to: ..."}]}
```

**History is maintained as `list[dict]` in `ContextManager`.** Serialized as `{"type":"response_item",...}` lines in rollout JSONL.

---

## Shell Execution

### Constants (from Codex source, exact values)
- **Default timeout:** 10,000 ms (10 seconds)
- **Output byte cap:** same as `DEFAULT_OUTPUT_BYTES_CAP` from pty utils (prevents OOM)
- **Max output delta events:** 10,000 per exec call (live stream capped; aggregate unlimited)
- **IO drain timeout after kill:** 2,000 ms
- **Read chunk size:** 8,192 bytes
- **Exit codes:** timeout → 124, SIGKILL → 137 (128 + 9)

### Execution Flow
```python
async def execute_command(params: ExecParams) -> ExecResult:
    # 1. Wrap command with sandbox runner (seatbelt/bwrap/restricted-token)
    wrapped = sandbox.wrap_command(params.command, params.cwd)
    
    # 2. Spawn subprocess with asyncio
    proc = await asyncio.create_subprocess_exec(
        *wrapped, cwd=params.cwd, env=params.env,
        stdout=PIPE, stderr=PIPE,
        start_new_session=True,  # new process group for group kill
    )
    
    # 3. Stream stdout/stderr with output cap
    # Emit ExecCommandOutputDeltaEvent for each chunk (max 10k events)
    # Aggregate full output (capped at EXEC_OUTPUT_MAX_BYTES)
    
    # 4. Enforce timeout — kill process GROUP on expiry
    try:
        await asyncio.wait_for(proc.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        # drain IO with 2s timeout
        exit_code = 124  # conventional timeout code
    
    return ExecResult(stdout, stderr, aggregated, exit_code, duration_ms)
```

### Capture Policies
- `ShellTool` — historical output cap + timeout (default for model-invoked commands)
- `FullBuffer` — no cap, no timeout (for internal trusted tools)

---

## Sandboxing

### Platform Implementations

**macOS — SeatbeltSandbox**
```python
def wrap_command(self, cmd, policy):
    profile = self._generate_seatbelt_profile(policy)
    profile_path = write_temp_file(profile)
    return ["/usr/bin/sandbox-exec", "-f", profile_path] + cmd
```

**Linux — BubblewrapSandbox** (falls back to NoSandbox if bwrap not found)
```python
def wrap_command(self, cmd, policy):
    args = ["bwrap"]
    if policy.mode == "read-only":
        args += ["--ro-bind", "/", "/"]
    elif policy.mode == "workspace-write":
        args += ["--ro-bind", "/", "/", "--bind", str(policy.cwd), str(policy.cwd), "--bind", "/tmp", "/tmp"]
    else:  # danger-full-access
        args += ["--dev-bind", "/", "/"]
    if not policy.network_access:
        args += ["--unshare-net"]
    return args + ["--"] + cmd
```

**Windows — RestrictedTokenSandbox** (pywin32, noop fallback with warning)

---

## Session Persistence & Rollout

### File layout
```
~/.bob/
├── config.toml
├── state.sqlite             # threads + memories tables
├── AGENTS.md                # user-level instructions
└── sessions/
    ├── 2025-04-04T12-30-00-{uuid}.jsonl
    └── ...
```

### JSONL Line Types
```jsonl
{"type":"session_meta","session_id":"...","model":"...","created_at":"...","cwd":"..."}
{"type":"turn_started","turn_id":"..."}
{"type":"user_message","items":[...]}
{"type":"response_item","item":{...}}                    // history item
{"type":"turn_context","turn_id":"...","model":"...","cwd":"...","sandbox_policy":"..."}
{"type":"compacted","message":"summary...","replacement_history":[...]}
{"type":"thread_rolled_back","num_turns":1}
{"type":"turn_complete","turn_id":"..."}
{"type":"turn_aborted","turn_id":"...","reason":"..."}
{"type":"session_ended","reason":"..."}
```

Writer opens in **append mode**. Crash-safe — resume skips incomplete final line.

### Rollout Reconstruction Algorithm (Resume / Fork)

**Scan NEWEST→OLDEST** to find the latest surviving compaction + metadata, then **replay OLDEST→NEWEST** for only the surviving tail:

```python
def reconstruct_history(rollout_items: list) -> ReconstructionResult:
    # Phase 1: scan backward
    base_history = None
    pending_rollbacks = 0
    rollout_suffix = rollout_items
    
    for i, item in enumerate(reversed(rollout_items)):
        if item.type == "compacted" and item.replacement_history:
            base_history = item.replacement_history
            rollout_suffix = rollout_items[len(rollout_items)-i:]  # items after this
            break
        if item.type == "thread_rolled_back":
            pending_rollbacks += item.num_turns
        if item.type == "turn_started":
            if segment_has_user_message and pending_rollbacks > 0:
                pending_rollbacks -= 1  # skip this turn
    
    # Phase 2: replay suffix forward
    history = base_history or []
    for item in rollout_suffix:
        if item.type == "response_item":
            history.append(item.item)
        elif item.type == "compacted" and item.replacement_history:
            history = item.replacement_history
        elif item.type == "thread_rolled_back":
            history = drop_last_n_user_turns(history, item.num_turns)
    
    return ReconstructionResult(history=history, previous_settings=...)
```

**Fork:** create new JSONL, write `{"type":"session_meta",...,"forked_from":"old_session_id"}`, replay reconstructed history as `response_item` lines, continue appending new turns.

---

## Compact Algorithm

Triggered by `/compact` slash command or automatically when history exceeds 85% of context window.

```
1. Build compaction prompt: current history + system prompt asking for CONTEXT CHECKPOINT COMPACTION
   Prompt text: "You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary 
   for another LLM that will resume the task. Include: Current progress and key decisions made,
   Important context/constraints/user preferences, What remains to be done (clear next steps),
   Any critical data/examples/references needed to continue. Be concise, structured."

2. Stream response from model (no tools, no sandbox — pure text generation)

3. Format summary: SUMMARY_PREFIX + "\n" + model_response

4. Select user messages (newest first, up to 20,000 tokens budget):
   selected = []
   remaining = 20_000
   for msg in reversed(user_messages_from_history):
       if not is_summary_message(msg):  # skip previous compaction summaries
           tokens = approx_tokens(msg)   # len // 4
           if tokens <= remaining:
               selected.insert(0, msg)
               remaining -= tokens
   
5. Build new_history:
   new_history = [as_user_message(m) for m in selected] + [as_user_message(summary)]

6. Write to rollout: {"type":"compacted","message":summary,"replacement_history":new_history}

7. Replace in-memory history with new_history

8. Recompute token counts

9. Emit: "Heads up: Long threads and multiple compactions can cause the model to be less 
   accurate. Start a new thread when possible to keep threads small and targeted."
```

**Token counting:** Use `usage.input_tokens` returned by API after each call. Pre-call estimate: `len(text) // 4`. Trigger at 85% of model's context window.

---

## Memory System (Two-Phase Pipeline)

### Layout
```
~/.bob/memories/
  ├── rollout_summaries/     # Phase 1 output: per-rollout extracted memories
  └── raw_memories.md        # Phase 2 output: consolidated memory file
```

### Phase 1 — Extraction
- Runs at session start in background
- Model: `gpt-5.1-codex-mini`, reasoning: Low
- Context: up to 70% of model context window (max ~150k tokens)
- Concurrency: max 8 simultaneous jobs
- Job lease: 3600 seconds
- For each unprocessed rollout JSONL: extract key memories → write to `rollout_summaries/`

### Phase 2 — Consolidation
- Model: `gpt-5.1-codex-mini` (or higher if configured), reasoning: Medium
- Reads all files from `rollout_summaries/`
- Consolidates into single `raw_memories.md`
- Injected into system prompt (max 5000 tokens)

### Control
- `Op::UpdateMemories` — trigger manual pipeline run
- `Op::DropMemories` — delete all memory files and DB rows
- `/debug-m-update` — debug trigger
- `/debug-m-drop` — debug drop

---

## Skills System

Skills are modular capabilities discovered from the filesystem.

### Discovery Paths (by scope)
- **User scope:** `~/.bob/skills/`
- **Repo scope:** `.bob/skills/` (in repo)
- **System scope:** bundled with bob

### Skill Metadata (from `skill.toml` in each skill dir)
```toml
name = "my-skill"
description = "What this skill does"

[interface]
display_name = "My Skill"
short_description = "Short version"
default_prompt = "Run my skill on the current project"
brand_color = "#FF0000"

[[dependencies.tools]]
type = "mcp"
value = "my-mcp-server"
command = "npx my-mcp-server"
```

### Flow
1. `Op::ListSkills` with optional cwds → `EventMsg::ListSkillsResponseEvent`
2. Skills show in `/skills` picker overlay
3. Selecting a skill: injects `default_prompt` into composer or sends directly
4. `EventMsg::SkillsUpdateAvailableEvent` when skill files change (file watcher)

---

## Review Mode

`/review` or `Op::Review` starts a dedicated review session.

### Review Targets
```python
class ReviewTarget(str, Enum):
    UNCOMMITTED_CHANGES = "uncommitted_changes"   # git diff (staged + unstaged + untracked)
    BASE_BRANCH = "base_branch"                    # against a specific branch
    COMMIT = "commit"                              # specific commit SHA
    CUSTOM = "custom"                              # arbitrary instructions

class ReviewRequest(BaseModel):
    target: ReviewTarget
    branch: Optional[str] = None        # for BASE_BRANCH
    sha: Optional[str] = None           # for COMMIT
    title: Optional[str] = None         # for COMMIT (human label)
    instructions: Optional[str] = None  # for CUSTOM
    user_facing_hint: Optional[str] = None
```

### Review Output
```python
class ReviewFinding(BaseModel):
    title: str
    body: str
    confidence_score: float  # 0.0-1.0
    priority: int
    file_path: Path
    line_start: int
    line_end: int

class ReviewOutputEvent(BaseModel):
    findings: list[ReviewFinding]
    overall_correctness: str
    overall_explanation: str
    overall_confidence_score: float
```

Events: `EnteredReviewModeEvent` → (agent runs review) → `ExitedReviewModeEvent` with findings.

---

## Multi-Agent System (v2)

### Thread Lifecycle
```python
class ThreadManager:
    threads: dict[ThreadId, CodexThread]
    
    async def create_thread(self, config: BobConfig, session_source: SessionSource) -> NewThread: ...
    async def fork_thread(self, source_id: ThreadId, fork_snapshot: ForkSnapshot) -> NewThread: ...
    async def shutdown_all(self, timeout_ms: int = 5000) -> ThreadShutdownReport: ...
    async def submit(self, thread_id: ThreadId, op: Op) -> str: ...  # returns submission_id
```

### Fork Snapshot Modes
```python
class ForkSnapshot:
    INTERRUPTED = "interrupted"   # interrupt mid-turn and fork there

class ForkBeforeNthUserMessage(BaseModel):
    n: int  # 0-indexed: fork before nth user message
```

### v2 Multi-Agent Tools
- **spawn_agent:** create new CodexThread with task, config overrides, initial prompt
- **send_message:** send a message to another thread (logged in both thread histories)
- **assign_task:** give a thread a specific task; wait for acknowledgment
- **wait_agent:** block until a thread's current turn completes
- **close_agent:** gracefully shut down a thread
- **list_agents:** return list of active threads with their statuses

Spawn depth limit: **5** (configurable). Circular spawning is detected and blocked.

### Inter-Agent Communication
```python
class InterAgentCommunication(BaseModel):
    author: AgentPath         # who sent it
    recipient: AgentPath      # who it's addressed to
    other_recipients: list[AgentPath]  # CC list
    content: str
    trigger_turn: bool        # whether to start a new turn in recipient
```

---

## Hooks System

Hooks run shell commands or prompts in response to agent lifecycle events.

### Hook Events
| Event | When |
|---|---|
| `session_start` | When session initializes |
| `pre_tool_use` | Before each tool call |
| `post_tool_use` | After each tool call |
| `user_prompt_submit` | When user submits a message |
| `stop` | When agent turn ends |

### Hook Config (in `~/.bob/config.toml`)
```toml
[[hooks]]
event = "pre_tool_use"
command = ["my-script.sh"]
mode = "sync"    # sync | async
scope = "turn"   # turn | thread
```

### Execution Modes
- **sync:** blocks tool execution until hook completes; exit code non-zero → block tool
- **async:** fires and forgets; doesn't block

Hooks emit `HookStartedEvent` and `HookCompletedEvent`.

---

## App Server Protocol (JSON-RPC 2.0)

### Transport
- `bob app-server` → WebSocket on configurable port
- `bob app-server --stdio` → stdin/stdout (default for VS Code extension)

### v2 Methods
```
thread/start           → TurnStartParams → TurnStartResponse
turn/steer             → TurnSteerParams (approve, interrupt, etc.)
turn/status            → TurnStatusParams → TurnStatus
threads/list           → ThreadLoadedListParams → ThreadLoadedListResponse
threads/resume         → ThreadResumeParams
threads/fork           → ThreadForkParams
config/get             → ConfigGetResponse
config/update          → ConfigUpdateParams
plugins/list           → PluginListResponse
plugins/install        → PluginInstallParams → PluginInstallResponse
plugins/uninstall      → PluginUninstallParams
skills/list            → SkillsListResponse
mcp/servers/list       → McpServersListResponse
feedback/upload        → FeedbackUploadParams
rate-limits/get        → RateLimitsResponse
```

### Event Streaming
The server pushes events as JSON-RPC notifications:
```json
{"jsonrpc": "2.0", "method": "event", "params": {"thread_id": "...", "event": {...}}}
```

---

## AGENTS.md System

### Loading Order (global → project, concatenated)
```
~/.bob/AGENTS.md          ← lowest priority (global)
{repo_root}/AGENTS.md
{parent_of_cwd}/AGENTS.md
{cwd}/AGENTS.md            ← highest priority (project)
```

### Scoping Rules (injected into system prompt)
- Each AGENTS.md applies to all files within its directory tree
- More-nested files take precedence over parent files
- Direct user instructions override all AGENTS.md instructions
- Files bob touches in a patch must comply with any in-scope AGENTS.md

### `/init` Command
Creates `AGENTS.md` in the current directory with starter template:
```markdown
# Project Instructions for Bob

## Code Style
- [Add your conventions here]

## Project Structure
- [Describe key directories]

## Testing
- [How to run tests]

## Notes
- [Any other context for the AI]
```

---

## TUI Layout

```
┌─────────────────────────────────────────────────────────┐
│ bob                                    gpt-5.1-codex-mini│  ← Header
├─────────────────────────────────────────────────────────┤
│ ▸ Step 1: Explore repo structure          ✓ completed   │  ← PlanWidget (when plan active)
│ ▸ Step 2: Edit config.py                  ⟳ in_progress │
│ ▸ Step 3: Run tests                       ○ pending     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  You  create a hello world script                       │
│                                                         │  ← ChatWidget (scrollable)
│  Bob  Sure! Let me create that for you.                 │
│  ┌─ shell ────────────────────────────────────────────┐ │
│  │ $ python hello.py                                  │ │
│  │ Hello, World!                                      │ │
│  └────────────────────────────────────────────────────┘ │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  ┌─ /re ─────────────────────────────────────────────┐  │  ← CommandPopup (on /)
│  │  /resume    resume a saved chat                   │  │
│  │  /review    review current changes                │  │
│  │  /rename    rename the current thread             │  │
│  └───────────────────────────────────────────────────┘  │
│  > /re█                                                  │  ← ComposerWidget
├─────────────────────────────────────────────────────────┤
│  workspace-write │ on-request │ gpt-5.1-codex-mini │ 4k │  ← Footer
└─────────────────────────────────────────────────────────┘
```

### Chat History Cells

The `ChatWidget` uses two cell types:
- **Committed cells** (`HistoryCell`) — finalized, immutable
- **Active cell** — current in-flight turn, mutates in place during streaming

**In-flight coalescing:** Multiple consecutive tool calls in the same turn are grouped into one visual block (not separate cells).

**Transcript overlay** (`Ctrl+T`) — shows committed cells + live tail of active cell.

### Approval Modal (ExecApprovalRequestEvent)
```
┌─ Approval Required ───────────────────────────────────────┐
│                                                           │
│  Bob wants to run:                                        │
│  $ rm -rf ./dist                                          │
│                                                           │
│  In: /home/user/myproject                                 │
│  Risk: file deletion (workspace-write sandbox)            │
│                                                           │
│  [y] Approve  [n] Deny  [a] Always Allow  [d] Deny & Stop │
└───────────────────────────────────────────────────────────┘
```

`[a]` = `ReviewDecision.APPROVED_FOR_SESSION` (never ask again this session)
`[d]` = `ReviewDecision.ABORT` (stop turn entirely)

### Patch Approval Modal (ApplyPatchApprovalRequestEvent)
Shows full colored diff of files being changed. Same y/n/a/d keys.

### Session Picker (for /resume and /fork)
- Paginated: **25 per page**, lazy load when cursor reaches bottom 5
- Sorted: newest first
- Columns: thread name, relative path, creation date, model
- Keys: `↑↓` navigate, `Enter` select (resume), `f` switch to fork mode, `Esc` cancel
- Fuzzy search: type to filter

---

## Implementation Phases

### Phase 1 — Foundation (2 weeks)
**Goal:** `bob` launches TUI, sends a message, Claude streams a response.

**Build:**
- `pyproject.toml` (all deps)
- `bob/protocol/ops.py` — ALL Op variants as Pydantic models
- `bob/protocol/events.py` — ALL EventMsg variants as Pydantic models
- `bob/protocol/config_types.py` — all enums
- `bob/config/schema.py` + `loader.py`
- `bob/client/openai_client.py` — Responses API streaming wrapper
- `bob/core/session.py` — `BobSession`: `asyncio.Queue[Submission]` + `asyncio.Queue[Event]` + agent loop task
- `bob/core/turn.py` — single turn: build input → stream → emit events (no tools)
- `bob/core/context_manager.py` — `ContextManager`: history list + `record_items()` + `raw_items()`
- `bob/tui/app.py` — minimal `BobApp`: header + chat + composer + footer
- `bob/tui/chat_widget.py` — streaming text display (committed + active cell)
- `bob/tui/composer.py` — plain text input only (no slash detection yet)
- `bob/tui/footer.py` — status bar
- `bob/cli/main.py` — `bob` → launches TUI; basic flag parsing
- `bob/prompts/system.md` — base system prompt

**Done when:** `bob` opens TUI, you type "hello", gpt-5.1-codex-mini streams a response.

---

### Phase 2 — Tool System + Shell + Approval (2 weeks)
**Goal:** Agent executes shell commands, applies patches, approval modals work.

**Build:**
- `bob/tools/registry.py` — `ToolRegistry`
- `bob/tools/shell.py` — `shell` tool: dispatches to `execute_command()`
- `bob/tools/apply_patch.py` — custom patch format parser + applier
- `bob/tools/apply_patch_instructions.md` — injected into system prompt
- `bob/tools/update_plan.py` — `update_plan` tool → emits `PlanUpdateEvent`
- `bob/tools/view_image.py` — `view_image` tool
- `bob/core/exec.py` — `execute_command()`: subprocess, streaming, output cap, timeout, process group kill
- `bob/core/turn.py` — extend with tool call loop: stream → execute tools → stream again
- `bob/sandbox/` — all 4 sandbox implementations
- `bob/tui/approval_widget.py` — exec approval modal (y/n/a/d)
- `bob/tui/patch_approval_widget.py` — patch approval modal with diff display
- `bob/tui/plan_widget.py` — plan checklist panel
- `bob/tui/diff_render.py` — colored diff display
- Approval pause/resume: `asyncio.Future` per `call_id`; resolved by `ExecApprovalOp`/`PatchApprovalOp`
- `bob exec PROMPT` — headless mode; stdin approval; `--json` JSONL output
- Interrupt: `asyncio.Event` cancel → process group kill → drain 2s → emit `TurnAbortedEvent`

**Done when:** Bob executes shell commands in TUI with approval modals; `bob exec` works.

---

### Phase 3 — Slash Commands + Session Persistence (2 weeks)
**Goal:** Full slash command system; sessions saved and resumable.

**Build:**
- `bob/tui/slash_commands.py` — `SlashCommand` enum (ALL commands from exact list above)
- `bob/tui/command_popup.py` — fuzzy autocomplete popup (appears on `/`, filters as you type)
- `bob/tui/composer.py` — slash detection, `!` prefix for shell passthrough, up-arrow history
- `bob/tui/resume_picker.py` — paginated session picker (25/page, lazy load, fork mode)
- `bob/tui/model_picker.py` — model picker for `/model`
- `bob/tui/approval_picker.py` — approval mode picker for `/approvals`
- `bob/tui/sandbox_picker.py` — sandbox mode picker for `/permissions`
- `bob/rollout/recorder.py` — async JSONL writer (all line types)
- `bob/rollout/state_db.py` — aiosqlite: threads table, migrations
- `bob/rollout/session_index.py` — name→id→path index
- `bob/core/rollout_reconstruction.py` — resume/fork algorithm
- Implement all core slash commands: `/new`, `/resume`, `/fork`, `/clear`, `/quit`, `/exit`, `/status`, `/diff`, `/rename`, `/compact`, `/ps`, `/stop`, `/debug-config`, `/rollout`

**Done when:** `/resume` shows picker; sessions survive restarts; `/fork` creates branched session.

---

### Phase 4 — TUI Polish + Remaining Slash Commands (1 week)
**Goal:** TUI looks and feels exactly like Codex.

**Build:**
- `bob/tui/markdown_render.py` — markdown → Textual rich text (code blocks, bold, inline code)
- `bob/tui/personality_picker.py` — for `/personality`
- `bob/tui/theme_picker.py` — for `/theme` (syntax highlight themes)
- `bob/tui/collab_picker.py` — for `/collab` and `/plan`
- `bob/tui/mcp_list_widget.py` — for `/mcp` tool listing
- `bob/tui/status_widget.py` — for `/status` (session info + token counts)
- `bob/tui/elicitation_widget.py` — MCP elicitation modal
- `bob/tui/user_input_widget.py` — `request_user_input` tool modal
- `/copy` — clipboard copy of last response
- `/mention` — file picker to attach file content to next message
- `/init` — create AGENTS.md with template
- `/diff` — `git diff --stat` display in chat
- `/experimental` — toggle experimental feature flags
- Transcript overlay (`Ctrl+T`)

**Done when:** Every slash command works; TUI is visually complete; keyboard shortcuts all work.

---

### Phase 5 — AGENTS.md + Instructions + Config Layers (1 week)
**Goal:** Project-level instructions and full config system.

**Build:**
- `bob/instructions/loader.py` — walk up from cwd loading AGENTS.md files + scoping rules
- `bob/core/environment_context.py` — build per-turn environment context (OS/cwd/shell/time/git)
- `bob/config/loader.py` — 4-layer merge with `tomllib`
- `bob/core/turn.py` — inject AGENTS.md + env context + permissions context into prompt
- `Op::OverrideTurnContext` — runtime session overrides (model switch, sandbox change, etc.)
- `/init` — create AGENTS.md with template
- Environment context delta injection (only re-inject when changed)

**Done when:** AGENTS.md files load per-project; `/model` switches model mid-session; env context updates between turns.

---

### Phase 6 — MCP Integration (1 week)
**Goal:** Bob connects to MCP servers; MCP tools available to model; bob runs as MCP server.

**Build:**
- `bob/mcp/client.py` — `McpServerConnection`: spawn subprocess, `mcp.ClientSession`, list/call tools
- `bob/mcp/manager.py` — `McpManager`: lifecycle, tool registry bridge, exponential backoff reconnect
- `bob/mcp/server.py` — bob-as-MCP-server (stdio transport)
- Register MCP tools into `ToolRegistry` (prefixed `{server}__{tool}`)
- `/mcp` slash command → `McpListWidget` showing all tools + server statuses
- MCP elicitation: `ElicitationRequestEvent` → `ElicitationWidget` modal → `ResolveElicitationOp`
- `Op::ListMcpTools`, `Op::RefreshMcpServers`, `Op::ReloadUserConfig`
- `bob mcp add/list/remove` CLI subcommands
- `McpStartupUpdateEvent` + `McpStartupCompleteEvent` displayed in footer during startup

**Done when:** Configured MCP servers' tools appear in model's tool list; bob runs as MCP server.

---

### Phase 7 — Multi-Agent + Review (1 week)
**Goal:** Sub-agent spawning; review mode; inter-agent communication.

**Build:**
- `bob/core/thread_manager.py` — `ThreadManager`: dict of `CodexThread`, fork, shutdown
- `bob/tools/multi_agent/` — all 6 v2 multi-agent tools
- `bob/core/agent/review.py` — review mode handler
- `/review` slash command → `Op::Review` → `EnteredReviewModeEvent` → agent runs → `ExitedReviewModeEvent`
- `/agent` / `/subagents` slash command — show thread picker, switch active thread
- `/ps` — list all active threads with status
- `/stop` — kill all background threads
- Spawn depth limit (5)
- `CollabAgent*Event` series emitted to TUI during multi-agent operations
- `Op::InterAgentCommunication` — cross-thread messages in history

**Done when:** Orchestrator agents spawn sub-agents; `/review` works; thread switching works in TUI.

---

### Phase 8 — Memory System + App Server (1 week)
**Goal:** Cross-session memories; JSON-RPC IDE integration.

**Build:**
- `bob/memories/phase1.py` — extraction pipeline (background, 8 concurrent)
- `bob/memories/phase2.py` — consolidation pipeline
- `bob/memories/storage.py` — SQLite + markdown file access
- Inject `raw_memories.md` into system prompt (max 5000 tokens)
- `Op::UpdateMemories`, `Op::DropMemories`, `/debug-m-update`, `/debug-m-drop`
- `bob/app_server/server.py` — JSON-RPC 2.0 WebSocket + stdio
- `bob/app_server/protocol_v2.py` — all v2 request/response Pydantic types
- `bob/app_server/message_processor.py` — route methods to ThreadManager
- `bob app-server` / `bob app-server --stdio` entry points

**Done when:** Memories persist and appear in context; VS Code extension can connect via app-server.

---

### Phase 9 — Hooks + Skills + Plugins + Realtime (1 week)
**Goal:** Full feature parity with Codex.

**Build:**
- `bob/hooks/runner.py` — hook execution (sync/async, pre/post tool-use, session-start)
- Hook config parsing + `HookStartedEvent` + `HookCompletedEvent`
- `bob/skills/manager.py` — skill discovery from `~/.bob/skills/`, `.bob/skills/`
- `bob/skills/watcher.py` — file watcher for skill changes
- `/skills` slash command → skills picker overlay
- `Op::ListSkills`, `EventMsg::ListSkillsResponseEvent`, `EventMsg::SkillsUpdateAvailableEvent`
- `bob/plugins/manager.py` — plugin install/list/uninstall
- `/plugins` slash command
- Realtime voice: `Op::RealtimeConversation*` → `EventMsg::RealtimeConversation*` (stub/partial)
- `/realtime`, `/settings` slash commands (voice mode UI)
- `Op::Undo` / `Op::ThreadRollback` — undo support
- `EventMsg::UndoStartedEvent` + `EventMsg::UndoCompletedEvent`

**Done when:** Hooks run; skills discoverable; plugins installable; undo works.

---

### Phase 10 — Context Management + Polish + Tests (1 week)
**Goal:** Robust context handling; full test suite; complete polish.

**Build:**
- Auto-compaction: check token count after each turn; trigger compact at 85%
- API retry: exponential backoff on stream errors; trim oldest on ContextWindowExceeded
- `bob/core/exec_policy.py` — trusted commands (safe commands list); execpolicy evaluation
- Shell completions: `bob completion bash|zsh`
- Rate limit tracking: `TokenCountEvent` → footer display
- `EventMsg::ModelRerouteEvent` — display when model is silently switched
- `EventMsg::DeprecationNoticeEvent` — display deprecation warnings
- `EventMsg::BackgroundEventEvent` — display background notifications
- Full test suite:
  - `tests/unit/` — protocol serialization, config loading, apply_patch parsing, sandbox wrapping
  - `tests/integration/` — agent loop with mock client, approval flow, session resume
  - `tests/e2e/` — Textual Pilot API for TUI automation

**Done when:** All tests pass; context never overflows; complete feature parity with Codex.

---

## Phase Timeline

| Phase | Duration | Milestone |
|---|---|---|
| 1 — Foundation | 2 weeks | TUI opens, Claude streams response |
| 2 — Tools + Shell | 2 weeks | Shell execution, apply_patch, approval modals |
| 3 — Slash + Sessions | 2 weeks | `/resume`, `/fork`, all sessions persist |
| 4 — TUI Polish | 1 week | Markdown, all slash commands, exact Codex feel |
| 5 — Instructions + Config | 1 week | AGENTS.md, env context, runtime overrides |
| 6 — MCP | 1 week | External tool servers, bob as MCP server |
| 7 — Multi-Agent + Review | 1 week | Sub-agents, `/review`, thread switching |
| 8 — Memory + App Server | 1 week | Cross-session memory, VS Code integration |
| 9 — Hooks + Skills + Plugins | 1 week | Full feature set |
| 10 — Polish + Tests | 1 week | All tests pass, complete parity |
| **Total** | **~13 weeks** | **Exact Codex parity in Python** |

---

## Dependencies (`pyproject.toml`)

```toml
[project]
name = "bob"
version = "0.1.0"
description = "bob — Your AI-Powered Development Partner"
requires-python = ">=3.11"

dependencies = [
    "openai>=1.30.0",          # Responses API + streaming
    "textual>=0.80.0",         # TUI framework
    "typer>=0.12.0",           # CLI
    "rich>=13.0.0",            # Terminal formatting
    "pydantic>=2.0.0",         # Data models + validation
    "aiosqlite>=0.20.0",       # Async SQLite
    "aiofiles>=23.0.0",        # Async file I/O
    "mcp>=1.0.0",              # MCP Python SDK
    "rapidfuzz>=3.0.0",        # Fuzzy matching for slash command autocomplete
    "pyperclip>=1.8.0",        # Clipboard (/copy command)
    "watchfiles>=0.21.0",      # File watcher (skills watcher)
    "tomllib; python_version < '3.11'",  # TOML parser (stdlib in 3.11+)
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov",
    "textual[dev]>=0.80.0",    # Textual Pilot API for e2e tests
]
windows = [
    "pywin32>=306",            # Windows restricted token sandbox
]

[project.scripts]
bob = "bob.cli.main:app"
```

---

## Codex Reference Files

When implementing, use these Rust files as ground truth:

| Bob module | Codex reference |
|---|---|
| `bob/protocol/ops.py` + `events.py` | `protocol/src/protocol.rs` |
| `bob/tui/slash_commands.py` | `tui/src/slash_command.rs` |
| `bob/tui/command_popup.py` | `tui/src/bottom_pane/command_popup.rs` |
| `bob/tui/composer.py` | `tui/src/bottom_pane/chat_composer.rs` |
| `bob/tui/app.py` | `tui/src/app.rs` |
| `bob/tui/chat_widget.py` | `tui/src/chatwidget.rs` |
| `bob/tui/resume_picker.py` | `tui/src/resume_picker.rs` |
| `bob/core/session.py` | `core/src/codex.rs` |
| `bob/core/turn.py` | `core/src/codex.rs` (agent loop) |
| `bob/core/exec.py` | `core/src/exec.rs` |
| `bob/core/compact.py` | `core/src/compact.rs` |
| `bob/core/rollout_reconstruction.py` | `core/src/codex/rollout_reconstruction.rs` |
| `bob/core/thread_manager.py` | `core/src/thread_manager.rs` |
| `bob/core/context_manager.py` | `core/src/context_manager/` |
| `bob/core/environment_context.py` | `core/src/context_manager/updates.rs` |
| `bob/tools/apply_patch.py` | `apply-patch/` crate |
| `bob/tools/apply_patch_instructions.md` | `apply-patch/apply_patch_tool_instructions.md` |
| `bob/prompts/system.md` | `core/prompt.md` |
| `bob/rollout/recorder.py` | `core/src/rollout/` |
| `bob/sandbox/macos.py` | `sandboxing/src/macos.rs` |
| `bob/sandbox/linux.py` | `linux-sandbox/` |
| `bob/memories/` | `core/src/memories/` |
| `bob/skills/manager.py` | `core/src/skills/` |
| `bob/hooks/runner.py` | `hooks/` crate |
| `bob/app_server/protocol_v2.py` | `app-server-protocol/src/protocol/v2.rs` |
| `bob/app_server/server.py` | `app-server/src/` |
| `bob/core/agent/review.py` | `core/src/agent/` (review handling) |
