from __future__ import annotations
from enum import Enum
from pathlib import Path
from typing import Optional, Union
from pydantic import BaseModel, Field
import uuid


class AskForApproval(str, Enum):
    UNLESS_TRUSTED = "untrusted"
    ON_FAILURE = "on-failure"
    ON_REQUEST = "on-request"
    NEVER = "never"


class GranularApproval(BaseModel):
    sandbox_approval: bool = True
    rules: bool = True
    skill_approval: bool = True
    request_permissions: bool = True
    mcp_elicitations: bool = True


class ApprovalsReviewer(str, Enum):
    USER = "user"


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


class OutputStyle(str, Enum):
    BRIEF = "brief"
    NORMAL = "normal"
    VERBOSE = "verbose"


class ReasoningEffort(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReasoningSummary(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class WebSearchMode(str, Enum):
    DISABLED = "disabled"
    CACHED = "cached"
    LIVE = "live"


class WebSearchContextSize(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ServiceTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    TEAM_OR_ENTERPRISE = "team_or_enterprise"


class WindowsSandboxLevel(str, Enum):
    DISABLED = "disabled"
    LOOSE = "loose"
    STRICT = "strict"


class CollaborationModeKind(str, Enum):
    DEFAULT = "default"
    PLAN = "plan"
    PAIR_PROGRAMMING = "pair_programming"
    EXECUTE = "execute"


class CollaborationModeSettings(BaseModel):
    model: Optional[str] = None
    reasoning_effort: Optional[ReasoningEffort] = None
    developer_instructions: Optional[str] = None


class CollaborationMode(BaseModel):
    mode: CollaborationModeKind = CollaborationModeKind.DEFAULT
    settings: CollaborationModeSettings = Field(default_factory=CollaborationModeSettings)


class SandboxPolicy(BaseModel):
    mode: SandboxMode = SandboxMode.WORKSPACE_WRITE
    writable_roots: list[Path] = Field(default_factory=list)
    network_access: bool = False
    cwd: Optional[Path] = None


class ExecCommandSource(str, Enum):
    AGENT = "agent"
    USER_SHELL = "user_shell"
    UNIFIED_EXEC_STARTUP = "unified_exec_startup"
    UNIFIED_EXEC_INTERACTION = "unified_exec_interaction"


class ExecCommandStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    DECLINED = "declined"


class ElicitationAction(str, Enum):
    APPROVE = "approve"
    DENY = "deny"
    CANCEL = "cancel"


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class RealtimeConversationVersion(str, Enum):
    V1 = "v1"
    V2 = "v2"


class HookEventName(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    SESSION_START = "session_start"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    POST_TURN = "post_turn"
    STOP = "stop"


class HookRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    STOPPED = "stopped"


class SkillScope(str, Enum):
    USER = "user"
    REPO = "repo"
    SYSTEM = "system"
    ADMIN = "admin"


class SessionSource(str, Enum):
    LOCAL = "local"
    CLOUD_API = "cloud_api"
    SUB_AGENT_COLLABORATION = "sub_agent_collaboration"
    SUB_AGENT_OTHER = "sub_agent_other"
