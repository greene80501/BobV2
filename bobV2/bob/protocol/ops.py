from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal, Optional, Union
from pydantic import BaseModel, Field

from bob.protocol.config_types import (
    AskForApproval,
    ElicitationAction,
    RealtimeConversationVersion,
    ReviewDecision,
    SandboxPolicy,
)
from bob.protocol.items import FileChange, UserInput
from bob.protocol.review_types import ReviewRequest


# ---------------------------------------------------------------------------
# UserTurnOp
# ---------------------------------------------------------------------------

class UserTurnOp(BaseModel):
    type: Literal["user_turn"] = "user_turn"
    items: list[UserInput]
    # Optional override: pass a pre-built developer/system message
    developer_message_override: Optional[str] = None


# ---------------------------------------------------------------------------
# InterruptOp
# ---------------------------------------------------------------------------

class InterruptOp(BaseModel):
    type: Literal["interrupt"] = "interrupt"
    # When True the agent should stop after the current tool call completes;
    # when False it interrupts immediately (hard stop).
    graceful: bool = True


# ---------------------------------------------------------------------------
# CleanBackgroundTerminalsOp
# ---------------------------------------------------------------------------

class CleanBackgroundTerminalsOp(BaseModel):
    type: Literal["clean_background_terminals"] = "clean_background_terminals"


# ---------------------------------------------------------------------------
# ExecApprovalOp
# ---------------------------------------------------------------------------

class ExecApprovalOp(BaseModel):
    type: Literal["exec_approval"] = "exec_approval"
    # The tool-call id that triggered the approval request
    tool_call_id: str
    decision: ReviewDecision
    # Optional reason shown to the agent when denied
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# PatchApprovalOp
# ---------------------------------------------------------------------------

class PatchApprovalOp(BaseModel):
    type: Literal["patch_approval"] = "patch_approval"
    tool_call_id: str
    decision: ReviewDecision
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# ResolveElicitationOp
# ---------------------------------------------------------------------------

class ResolveElicitationOp(BaseModel):
    type: Literal["resolve_elicitation"] = "resolve_elicitation"
    elicitation_id: str
    action: ElicitationAction
    # Free-form data filled in by the user (if action == APPROVE)
    data: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# UserInputAnswerOp
# ---------------------------------------------------------------------------

class UserInputAnswerOp(BaseModel):
    type: Literal["user_input_answer"] = "user_input_answer"
    # The request_id from the corresponding UserInputRequestEvent
    request_id: str
    answer: str


# ---------------------------------------------------------------------------
# RequestPermissionsResponseOp
# ---------------------------------------------------------------------------

class RequestPermissionsResponseOp(BaseModel):
    type: Literal["request_permissions_response"] = "request_permissions_response"


# ---------------------------------------------------------------------------
# PlanApprovalOp
# ---------------------------------------------------------------------------

class PlanApprovalOp(BaseModel):
    """User's response to a plan approval request."""
    type: Literal["plan_approval"] = "plan_approval"
    approved: bool
    feedback: str = ""  # Optional feedback if rejected



class NetworkApprovalOp(BaseModel):
    """User's response to a network approval request."""
    type: Literal["network_approval"] = "network_approval"
    url: str
    domain: str
    approved: bool
    approve_always: bool = False  # Approve this domain for the entire session




    request_id: str
    granted: bool
    # Permissions that were actually granted (subset of requested)
    granted_permissions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# DynamicToolResponseOp
# ---------------------------------------------------------------------------

class DynamicToolResponseOp(BaseModel):
    type: Literal["dynamic_tool_response"] = "dynamic_tool_response"
    tool_call_id: str
    # JSON-serialisable result to return to the model
    result: Any


# ---------------------------------------------------------------------------
# OverrideTurnContextOp
# ---------------------------------------------------------------------------

class OverrideTurnContextOp(BaseModel):
    type: Literal["override_turn_context"] = "override_turn_context"
    # Replace the current sandbox policy for the remainder of the turn
    sandbox_policy: Optional[SandboxPolicy] = None
    # Replace the effective model
    model: Optional[str] = None
    # Additional developer instructions injected at the top of the next turn
    extra_instructions: Optional[str] = None


# ---------------------------------------------------------------------------
# CompactOp
# ---------------------------------------------------------------------------

class CompactOp(BaseModel):
    type: Literal["compact"] = "compact"
    # Optional user-visible hint for what to preserve during compaction
    hint: Optional[str] = None


# ---------------------------------------------------------------------------
# AddToHistoryOp
# ---------------------------------------------------------------------------

class AddToHistoryOp(BaseModel):
    type: Literal["add_to_history"] = "add_to_history"
    # Raw message dicts to inject into the conversation history
    messages: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# SetThreadNameOp
# ---------------------------------------------------------------------------

class SetThreadNameOp(BaseModel):
    type: Literal["set_thread_name"] = "set_thread_name"
    name: str


# ---------------------------------------------------------------------------
# UndoOp
# ---------------------------------------------------------------------------

class UndoOp(BaseModel):
    type: Literal["undo"] = "undo"
    # Number of turns to undo (default 1)
    turns: int = 1


# ---------------------------------------------------------------------------
# ThreadRollbackOp
# ---------------------------------------------------------------------------

class ThreadRollbackOp(BaseModel):
    type: Literal["thread_rollback"] = "thread_rollback"
    # Rollback to just before this submission id
    to_submission_id: str


# ---------------------------------------------------------------------------
# ShutdownOp
# ---------------------------------------------------------------------------

class ShutdownOp(BaseModel):
    type: Literal["shutdown"] = "shutdown"
    # Exit code the process should use
    exit_code: int = 0
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# SwarmAuthorizationOp — user's response to a SwarmOfferEvent or SwarmPlanReadyEvent
# ---------------------------------------------------------------------------

class SwarmAuthorizationOp(BaseModel):
    type: Literal["swarm_authorization"] = "swarm_authorization"
    # run_id matches the offer_id from SwarmOfferEvent or run_id from SwarmPlanReadyEvent
    run_id: str
    approved: bool
    feedback: str = ""  # optional reason when declined


# ---------------------------------------------------------------------------
# RunSwarmOp — explicit user invocation of swarm mode (e.g. /swarm <task>)
# ---------------------------------------------------------------------------

class RunSwarmOp(BaseModel):
    type: Literal["run_swarm"] = "run_swarm"
    task: str


# ---------------------------------------------------------------------------
# ReviewOp
# ---------------------------------------------------------------------------

class ReviewOp(BaseModel):
    type: Literal["review"] = "review"
    request: ReviewRequest


# ---------------------------------------------------------------------------
# RunUserShellCommandOp
# ---------------------------------------------------------------------------

class RunUserShellCommandOp(BaseModel):
    type: Literal["run_user_shell_command"] = "run_user_shell_command"
    command: str
    # Working directory; defaults to session cwd
    cwd: Optional[str] = None
    # Environment variable overrides
    env: dict[str, str] = Field(default_factory=dict)
    # If True, run in background and do not wait for completion
    background: bool = False


# ---------------------------------------------------------------------------
# ListModelsOp
# ---------------------------------------------------------------------------

class ListModelsOp(BaseModel):
    type: Literal["list_models"] = "list_models"


# ---------------------------------------------------------------------------
# ListMcpToolsOp
# ---------------------------------------------------------------------------

class ListMcpToolsOp(BaseModel):
    type: Literal["list_mcp_tools"] = "list_mcp_tools"
    # Optional filter by MCP server name
    server_name: Optional[str] = None


# ---------------------------------------------------------------------------
# RefreshMcpServersOp
# ---------------------------------------------------------------------------

class RefreshMcpServersOp(BaseModel):
    type: Literal["refresh_mcp_servers"] = "refresh_mcp_servers"


# ---------------------------------------------------------------------------
# ReloadUserConfigOp
# ---------------------------------------------------------------------------

class ReloadUserConfigOp(BaseModel):
    type: Literal["reload_user_config"] = "reload_user_config"


# ---------------------------------------------------------------------------
# ListSkillsOp
# ---------------------------------------------------------------------------

class ListSkillsOp(BaseModel):
    type: Literal["list_skills"] = "list_skills"
    cwd: Optional[str] = None


# ---------------------------------------------------------------------------
# GetHistoryEntryRequestOp
# ---------------------------------------------------------------------------

class GetHistoryEntryRequestOp(BaseModel):
    type: Literal["get_history_entry_request"] = "get_history_entry_request"
    # Which history entry to fetch (0 = most recent turn)
    index: int = 0


# ---------------------------------------------------------------------------
# DropMemoriesOp
# ---------------------------------------------------------------------------

class DropMemoriesOp(BaseModel):
    type: Literal["drop_memories"] = "drop_memories"
    # Memory ids to drop; empty list means drop ALL memories
    memory_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# UpdateMemoriesOp
# ---------------------------------------------------------------------------

class MemoryUpdate(BaseModel):
    id: Optional[str] = None  # None = create new memory
    content: str
    tags: list[str] = Field(default_factory=list)


class UpdateMemoriesOp(BaseModel):
    type: Literal["update_memories"] = "update_memories"
    updates: list[MemoryUpdate]


# ---------------------------------------------------------------------------
# InterAgentCommunicationOp
# ---------------------------------------------------------------------------

class InterAgentCommunicationOp(BaseModel):
    type: Literal["inter_agent_communication"] = "inter_agent_communication"
    # Destination agent thread id
    target_thread_id: str
    # Freeform payload
    payload: dict[str, Any]
    # Whether the sender expects a response
    await_response: bool = False


# ---------------------------------------------------------------------------
# RealtimeConversationStartOp
# ---------------------------------------------------------------------------

class RealtimeConversationStartOp(BaseModel):
    type: Literal["realtime_conversation_start"] = "realtime_conversation_start"
    version: RealtimeConversationVersion = RealtimeConversationVersion.V2
    # Optional initial text prompt
    initial_prompt: Optional[str] = None
    # Extra parameters passed through to the realtime API
    extra_params: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# RealtimeConversationAudioOp
# ---------------------------------------------------------------------------

class RealtimeConversationAudioOp(BaseModel):
    type: Literal["realtime_conversation_audio"] = "realtime_conversation_audio"
    # Base64-encoded PCM16 audio chunk
    audio_b64: str
    # Whether this is the final chunk (triggers VAD commit)
    is_final: bool = False


# ---------------------------------------------------------------------------
# RealtimeConversationTextOp
# ---------------------------------------------------------------------------

class RealtimeConversationTextOp(BaseModel):
    type: Literal["realtime_conversation_text"] = "realtime_conversation_text"
    text: str


# ---------------------------------------------------------------------------
# RealtimeConversationCloseOp
# ---------------------------------------------------------------------------

class RealtimeConversationCloseOp(BaseModel):
    type: Literal["realtime_conversation_close"] = "realtime_conversation_close"
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Discriminated union of all Op variants
# ---------------------------------------------------------------------------

Op = Annotated[
    Union[
        UserTurnOp,
        InterruptOp,
        CleanBackgroundTerminalsOp,
        ExecApprovalOp,
        PatchApprovalOp,
        NetworkApprovalOp,
        ResolveElicitationOp,
        UserInputAnswerOp,
        RequestPermissionsResponseOp,
        DynamicToolResponseOp,
        OverrideTurnContextOp,
        CompactOp,
        AddToHistoryOp,
        SetThreadNameOp,
        UndoOp,
        ThreadRollbackOp,
        ShutdownOp,
        ReviewOp,
        RunUserShellCommandOp,
        ListModelsOp,
        ListMcpToolsOp,
        RefreshMcpServersOp,
        ReloadUserConfigOp,
        ListSkillsOp,
        GetHistoryEntryRequestOp,
        DropMemoriesOp,
        UpdateMemoriesOp,
        InterAgentCommunicationOp,
        RealtimeConversationStartOp,
        RealtimeConversationAudioOp,
        RealtimeConversationTextOp,
        RealtimeConversationCloseOp,
        SwarmAuthorizationOp,
        RunSwarmOp,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Submission envelope
# ---------------------------------------------------------------------------

class Submission(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    op: Op
