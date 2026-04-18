from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union
from pydantic import BaseModel, Field

from bob.protocol.config_types import (
    ExecCommandSource,
    ExecCommandStatus,
    HookEventName,
    HookRunStatus,
    ReasoningEffort,
    ReviewDecision,
    SandboxMode,
    SandboxPolicy,
    SessionSource,
    StepStatus,
    WebSearchMode,
)
from bob.protocol.items import FileChange, ResponseItem, SkillMetadata, SkillsListEntry
from bob.protocol.plan_types import PlanItemArg
from bob.protocol.review_types import ReviewFinding, ReviewOutputEvent


# ===========================================================================
# Session lifecycle
# ===========================================================================

class SessionStartedEvent(BaseModel):
    type: Literal["session_started"] = "session_started"
    session_id: str
    thread_id: str
    source: SessionSource
    model: str
    cwd: str


class SessionEndedEvent(BaseModel):
    type: Literal["session_ended"] = "session_ended"
    session_id: str
    reason: Optional[str] = None
    exit_code: int = 0


class ThreadNameSetEvent(BaseModel):
    type: Literal["thread_name_set"] = "thread_name_set"
    name: str


# ===========================================================================
# Turn lifecycle
# ===========================================================================

class TurnStartedEvent(BaseModel):
    type: Literal["turn_started"] = "turn_started"
    turn_id: str


class TurnEndedEvent(BaseModel):
    type: Literal["turn_ended"] = "turn_ended"
    turn_id: str
    # Total token usage for this turn
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0  # Tokens read from cache (cost savings)


class TurnInterruptedEvent(BaseModel):
    type: Literal["turn_interrupted"] = "turn_interrupted"
    turn_id: str
    graceful: bool


# ===========================================================================
# Streaming text / reasoning
# ===========================================================================

class TextDeltaEvent(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    delta: str


class TextFinalEvent(BaseModel):
    type: Literal["text_final"] = "text_final"
    text: str


class ReasoningDeltaEvent(BaseModel):
    type: Literal["reasoning_delta"] = "reasoning_delta"
    delta: str


class ReasoningSummaryEvent(BaseModel):
    type: Literal["reasoning_summary"] = "reasoning_summary"
    summary: str


# ===========================================================================
# Tool execution
# ===========================================================================

class ToolCallStartedEvent(BaseModel):
    type: Literal["tool_call_started"] = "tool_call_started"
    tool_call_id: str
    tool_name: str
    tool_input: dict[str, Any]


class ToolCallCompletedEvent(BaseModel):
    type: Literal["tool_call_completed"] = "tool_call_completed"
    tool_call_id: str
    tool_name: str
    # JSON-serialisable output
    output: Any
    # Wall-clock duration in milliseconds
    duration_ms: int = 0
    error: Optional[str] = None


# ===========================================================================
# Shell / exec
# ===========================================================================

class ExecStartedEvent(BaseModel):
    type: Literal["exec_started"] = "exec_started"
    tool_call_id: str
    command: list[str]
    cwd: str
    source: ExecCommandSource
    sandbox_mode: SandboxMode


class ExecOutputEvent(BaseModel):
    type: Literal["exec_output"] = "exec_output"
    tool_call_id: str
    # "stdout" | "stderr"
    stream: str
    data: str


class ExecCompletedEvent(BaseModel):
    type: Literal["exec_completed"] = "exec_completed"
    tool_call_id: str
    exit_code: int
    status: ExecCommandStatus
    duration_ms: int = 0


# Approval flow for shell commands
class ExecApprovalRequestedEvent(BaseModel):
    type: Literal["exec_approval_requested"] = "exec_approval_requested"
    tool_call_id: str
    command: list[str]
    cwd: str
    reason: str
    # Suggested safe alternatives if any
    alternatives: list[str] = Field(default_factory=list)


class ExecApprovalResolvedEvent(BaseModel):
    type: Literal["exec_approval_resolved"] = "exec_approval_resolved"
    tool_call_id: str
    decision: ReviewDecision
    reason: Optional[str] = None


# ===========================================================================
# Patch / file changes
# ===========================================================================

class PatchApprovalRequestedEvent(BaseModel):
    type: Literal["patch_approval_requested"] = "patch_approval_requested"
    tool_call_id: str
    changes: list[FileChange]
    patch_text: str


class PatchApprovalResolvedEvent(BaseModel):
    type: Literal["patch_approval_resolved"] = "patch_approval_resolved"
    tool_call_id: str
    decision: ReviewDecision
    reason: Optional[str] = None


class FilesChangedEvent(BaseModel):
    type: Literal["files_changed"] = "files_changed"
    changes: list[FileChange]


# ===========================================================================
# Plan
# ===========================================================================

class PlanUpdatedEvent(BaseModel):
    type: Literal["plan_updated"] = "plan_updated"
    explanation: Optional[str] = None
    plan: list[PlanItemArg]


class PlanStepStatusEvent(BaseModel):
    type: Literal["plan_step_status"] = "plan_step_status"
    step: str
    status: StepStatus


# ===========================================================================
# Approvals / permissions / elicitations
# ===========================================================================

class UserInputRequestEvent(BaseModel):
    type: Literal["user_input_request"] = "user_input_request"
    request_id: str
    prompt: str
    # If set, show a multi-choice picker instead of free-form input
    choices: Optional[list[str]] = None
    default: Optional[str] = None


class UserInputAnsweredEvent(BaseModel):
    type: Literal["user_input_answered"] = "user_input_answered"
    request_id: str
    answer: str


class RequestPermissionsEvent(BaseModel):
    type: Literal["request_permissions"] = "request_permissions"
    request_id: str
    permissions: list[str]
    reason: Optional[str] = None


class RequestPermissionsResponseEvent(BaseModel):
    type: Literal["request_permissions_response"] = "request_permissions_response"
    request_id: str
    granted: bool
    granted_permissions: list[str] = Field(default_factory=list)


class ElicitationRequestedEvent(BaseModel):
    type: Literal["elicitation_requested"] = "elicitation_requested"
    elicitation_id: str
    # JSON Schema describing the data to collect
    schema_: dict[str, Any] = Field(alias="schema")
    description: Optional[str] = None

    model_config = {"populate_by_name": True}


class ElicitationResolvedEvent(BaseModel):
    type: Literal["elicitation_resolved"] = "elicitation_resolved"
    elicitation_id: str


class PlanApprovalRequestedEvent(BaseModel):
    """Emitted when model exits plan mode and requests approval."""
    type: Literal["plan_approval_requested"] = "plan_approval_requested"
    plan_summary: str


class PlanApprovedEvent(BaseModel):
    """Emitted after user approves the plan."""
    type: Literal["plan_approved"] = "plan_approved"


class PlanRejectedEvent(BaseModel):
    """Emitted after user rejects the plan."""
    type: Literal["plan_rejected"] = "plan_rejected"
    reason: str = ""


    action: str  # ElicitationAction value


class NetworkApprovalRequestedEvent(BaseModel):
    """Emitted when a tool attempts network access to an unapproved domain."""
    type: Literal["network_approval_requested"] = "network_approval_requested"
    url: str
    domain: str
    tool_name: str
    request_id: str = ""



    data: Optional[dict[str, Any]] = None


# ===========================================================================
# Sandbox
# ===========================================================================

class SandboxInitialisedEvent(BaseModel):
    type: Literal["sandbox_initialised"] = "sandbox_initialised"
    policy: SandboxPolicy


class SandboxPolicyChangedEvent(BaseModel):
    type: Literal["sandbox_policy_changed"] = "sandbox_policy_changed"
    old_policy: SandboxPolicy
    new_policy: SandboxPolicy


# ===========================================================================
# MCP
# ===========================================================================

class McpServerConnectedEvent(BaseModel):
    type: Literal["mcp_server_connected"] = "mcp_server_connected"
    server_name: str
    tool_count: int


class McpServerDisconnectedEvent(BaseModel):
    type: Literal["mcp_server_disconnected"] = "mcp_server_disconnected"
    server_name: str
    reason: Optional[str] = None


class McpToolsListedEvent(BaseModel):
    type: Literal["mcp_tools_listed"] = "mcp_tools_listed"
    server_name: Optional[str] = None
    tools: list[dict[str, Any]]


class McpServersRefreshedEvent(BaseModel):
    type: Literal["mcp_servers_refreshed"] = "mcp_servers_refreshed"
    connected: list[str]
    failed: list[str]


# ===========================================================================
# Models
# ===========================================================================

class ModelsListedEvent(BaseModel):
    type: Literal["models_listed"] = "models_listed"
    models: list[str]


# ===========================================================================
# Config
# ===========================================================================

class UserConfigReloadedEvent(BaseModel):
    type: Literal["user_config_reloaded"] = "user_config_reloaded"
    # Serialised snapshot of the new config
    config_snapshot: dict[str, Any]


# ===========================================================================
# Skills
# ===========================================================================

class SkillsListedEvent(BaseModel):
    type: Literal["skills_listed"] = "skills_listed"
    entries: list[SkillsListEntry]


class SkillStartedEvent(BaseModel):
    type: Literal["skill_started"] = "skill_started"
    skill_name: str
    cwd: str


class SkillEndedEvent(BaseModel):
    type: Literal["skill_ended"] = "skill_ended"
    skill_name: str
    success: bool
    error: Optional[str] = None


class SkillApprovalRequestedEvent(BaseModel):
    type: Literal["skill_approval_requested"] = "skill_approval_requested"
    skill_name: str
    description: str
    metadata: Optional[dict[str, Any]] = None


class SkillApprovalResolvedEvent(BaseModel):
    type: Literal["skill_approval_resolved"] = "skill_approval_resolved"
    skill_name: str
    decision: ReviewDecision


# ===========================================================================
# Memories
# ===========================================================================

class MemoriesDroppedEvent(BaseModel):
    type: Literal["memories_dropped"] = "memories_dropped"
    memory_ids: list[str]


class MemoriesUpdatedEvent(BaseModel):
    type: Literal["memories_updated"] = "memories_updated"
    # Serialised list of updated memory records
    memories: list[dict[str, Any]]


# ===========================================================================
# History
# ===========================================================================

class HistoryEntryResponseEvent(BaseModel):
    type: Literal["history_entry_response"] = "history_entry_response"
    index: int
    # Serialised list of ResponseItem
    messages: list[dict[str, Any]]


class HistoryCompactedEvent(BaseModel):
    type: Literal["history_compacted"] = "history_compacted"
    # Summary injected to represent the compacted portion
    summary: str
    turns_removed: int


class ContextCompactionEvent(BaseModel):
    type: Literal["context_compaction"] = "context_compaction"
    reason: str
    token_before: int
    token_after: int
    success: bool


class UndoCompletedEvent(BaseModel):
    type: Literal["undo_completed"] = "undo_completed"
    turns_removed: int


class ThreadRollbackCompletedEvent(BaseModel):
    type: Literal["thread_rollback_completed"] = "thread_rollback_completed"
    to_submission_id: str


# ===========================================================================
# Hooks
# ===========================================================================

class HookRunStartedEvent(BaseModel):
    type: Literal["hook_run_started"] = "hook_run_started"
    hook_id: str
    event_name: HookEventName
    command: str


class HookRunCompletedEvent(BaseModel):
    type: Literal["hook_run_completed"] = "hook_run_completed"
    hook_id: str
    event_name: HookEventName
    status: HookRunStatus
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    duration_ms: int = 0


class HookBlockedEvent(BaseModel):
    type: Literal["hook_blocked"] = "hook_blocked"
    hook_id: str
    reason: str


# ===========================================================================
# Web search
# ===========================================================================

class WebSearchStartedEvent(BaseModel):
    type: Literal["web_search_started"] = "web_search_started"
    query: str
    mode: WebSearchMode


class WebSearchCompletedEvent(BaseModel):
    type: Literal["web_search_completed"] = "web_search_completed"
    query: str
    result_count: int
    cached: bool


# ===========================================================================
# Review
# ===========================================================================

class ReviewStartedEvent(BaseModel):
    type: Literal["review_started"] = "review_started"
    target_kind: str


class ReviewProgressEvent(BaseModel):
    type: Literal["review_progress"] = "review_progress"
    message: str
    percent: Optional[int] = None  # 0-100


class ReviewCompletedEvent(BaseModel):
    type: Literal["review_completed"] = "review_completed"
    output: ReviewOutputEvent


class ReviewFindingEvent(BaseModel):
    type: Literal["review_finding"] = "review_finding"
    finding: ReviewFinding


# ===========================================================================
# Background terminals
# ===========================================================================

class BackgroundTerminalOutputEvent(BaseModel):
    type: Literal["background_terminal_output"] = "background_terminal_output"
    terminal_id: str
    stream: str  # "stdout" | "stderr"
    data: str


class BackgroundTerminalsCleanedEvent(BaseModel):
    type: Literal["background_terminals_cleaned"] = "background_terminals_cleaned"
    terminal_ids: list[str]


# ===========================================================================
# Inter-agent communication
# ===========================================================================

class InterAgentMessageEvent(BaseModel):
    type: Literal["inter_agent_message"] = "inter_agent_message"
    source_thread_id: str
    target_thread_id: str
    payload: dict[str, Any]


class InterAgentResponseEvent(BaseModel):
    type: Literal["inter_agent_response"] = "inter_agent_response"
    source_thread_id: str
    payload: dict[str, Any]


# ===========================================================================
# Realtime conversation
# ===========================================================================

class RealtimeConversationStartedEvent(BaseModel):
    type: Literal["realtime_conversation_started"] = "realtime_conversation_started"
    session_id: str


class RealtimeAudioDeltaEvent(BaseModel):
    type: Literal["realtime_audio_delta"] = "realtime_audio_delta"
    # Base64-encoded PCM16 audio
    audio_b64: str


class RealtimeTranscriptDeltaEvent(BaseModel):
    type: Literal["realtime_transcript_delta"] = "realtime_transcript_delta"
    delta: str
    # "input" | "output"
    role: str


class RealtimeConversationClosedEvent(BaseModel):
    type: Literal["realtime_conversation_closed"] = "realtime_conversation_closed"
    reason: Optional[str] = None


# ===========================================================================
# Dynamic tool (user-defined tools resolved at runtime)
# ===========================================================================

class DynamicToolCallEvent(BaseModel):
    type: Literal["dynamic_tool_call"] = "dynamic_tool_call"
    tool_call_id: str
    tool_name: str
    tool_input: dict[str, Any]


# ===========================================================================
# Errors / generic notifications
# ===========================================================================

class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    code: Optional[str] = None
    # Whether the session can continue after this error
    fatal: bool = False
    details: Optional[dict[str, Any]] = None


class WarningEvent(BaseModel):
    type: Literal["warning"] = "warning"
    message: str
    code: Optional[str] = None


class InfoEvent(BaseModel):
    type: Literal["info"] = "info"
    message: str


class DebugEvent(BaseModel):
    type: Literal["debug"] = "debug"
    message: str
    data: Optional[dict[str, Any]] = None


# ===========================================================================
# Token budget / cost
# ===========================================================================

class TokenBudgetEvent(BaseModel):
    type: Literal["token_budget"] = "token_budget"
    used_tokens: int
    budget_tokens: int
    # Fraction 0.0-1.0
    fraction_used: float


class CostEstimateEvent(BaseModel):
    type: Literal["cost_estimate"] = "cost_estimate"
    # Estimated cost in USD
    estimated_cost_usd: float
    input_tokens: int
    output_tokens: int


# ===========================================================================
# IDE integration
# ===========================================================================

class IDEShowDiffEvent(BaseModel):
    """Request the connected IDE to open a diff view for the given content."""
    type: Literal["ide_show_diff"] = "ide_show_diff"
    # Raw git diff output (unified diff format)
    diff: str
    # Optional base ref for context (e.g. "HEAD", "main")
    base_ref: str = "HEAD"
    title: str = "git diff"


# ===========================================================================
# Discriminated union of ALL EventMsg variants
# ===========================================================================

EventMsg = Annotated[
    Union[
        # Session lifecycle
        SessionStartedEvent,
        SessionEndedEvent,
        ThreadNameSetEvent,
        # Turn lifecycle
        TurnStartedEvent,
        TurnEndedEvent,
        TurnInterruptedEvent,
        # Streaming text / reasoning
        TextDeltaEvent,
        TextFinalEvent,
        ReasoningDeltaEvent,
        ReasoningSummaryEvent,
        # Tool execution
        ToolCallStartedEvent,
        ToolCallCompletedEvent,
        # Shell / exec
        ExecStartedEvent,
        ExecOutputEvent,
        ExecCompletedEvent,
        ExecApprovalRequestedEvent,
        ExecApprovalResolvedEvent,
        # Patch / file changes
        PatchApprovalRequestedEvent,
        PatchApprovalResolvedEvent,
        FilesChangedEvent,
        # Network
        NetworkApprovalRequestedEvent,
        # Plan
        PlanUpdatedEvent,
        PlanStepStatusEvent,
        # Approvals / permissions / elicitations
        UserInputRequestEvent,
        UserInputAnsweredEvent,
        RequestPermissionsEvent,
        RequestPermissionsResponseEvent,
        ElicitationRequestedEvent,
        ElicitationResolvedEvent,
        # Sandbox
        SandboxInitialisedEvent,
        SandboxPolicyChangedEvent,
        # MCP
        McpServerConnectedEvent,
        McpServerDisconnectedEvent,
        McpToolsListedEvent,
        McpServersRefreshedEvent,
        # Models
        ModelsListedEvent,
        # Config
        UserConfigReloadedEvent,
        # Skills
        SkillsListedEvent,
        SkillStartedEvent,
        SkillEndedEvent,
        SkillApprovalRequestedEvent,
        SkillApprovalResolvedEvent,
        # Memories
        MemoriesDroppedEvent,
        MemoriesUpdatedEvent,
        # History
        HistoryEntryResponseEvent,
        HistoryCompactedEvent,
        ContextCompactionEvent,
        UndoCompletedEvent,
        ThreadRollbackCompletedEvent,
        # Hooks
        HookRunStartedEvent,
        HookRunCompletedEvent,
        HookBlockedEvent,
        # Web search
        WebSearchStartedEvent,
        WebSearchCompletedEvent,
        # Review
        ReviewStartedEvent,
        ReviewProgressEvent,
        ReviewCompletedEvent,
        ReviewFindingEvent,
        # Background terminals
        BackgroundTerminalOutputEvent,
        BackgroundTerminalsCleanedEvent,
        # Inter-agent
        InterAgentMessageEvent,
        InterAgentResponseEvent,
        # Realtime conversation
        RealtimeConversationStartedEvent,
        RealtimeAudioDeltaEvent,
        RealtimeTranscriptDeltaEvent,
        RealtimeConversationClosedEvent,
        # Dynamic tool
        DynamicToolCallEvent,
        # Errors / notifications
        ErrorEvent,
        WarningEvent,
        InfoEvent,
        DebugEvent,
        # Token budget / cost
        TokenBudgetEvent,
        CostEstimateEvent,
        # IDE integration
        IDEShowDiffEvent,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Top-level Event envelope
# ---------------------------------------------------------------------------

class Event(BaseModel):
    """Wraps an EventMsg and ties it back to the Submission that triggered it."""

    id: str  # submission id this event corresponds to
    msg: EventMsg
