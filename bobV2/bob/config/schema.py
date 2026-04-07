from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from bob.protocol.config_types import (
    AskForApproval,
    ApprovalsReviewer,
    CollaborationMode,
    CollaborationModeKind,
    CollaborationModeSettings,
    GranularApproval,
    OutputStyle,
    Personality,
    ReasoningEffort,
    ReasoningSummary,
    SandboxMode,
    ServiceTier,
    WebSearchContextSize,
    WebSearchMode,
    WindowsSandboxLevel,
)


# ---------------------------------------------------------------------------
# MCP server configuration
# ---------------------------------------------------------------------------

class McpServerConfig(BaseModel):
    command: list[str]
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Web search tool configuration
# ---------------------------------------------------------------------------

class WebSearchToolConfig(BaseModel):
    context_size: Optional[WebSearchContextSize] = None
    allowed_domains: Optional[list[str]] = None
    location: Optional[str] = None


# ---------------------------------------------------------------------------
# Hook configuration
# ---------------------------------------------------------------------------

class HookConfig(BaseModel):
    """A single hook entry — maps an event name to a shell command."""
    event: str  # HookEventName value
    command: str
    # Optional glob/tool-name filter (e.g. only run on bash_exec)
    match_tool: Optional[str] = None
    # Timeout in seconds; 0 means no timeout
    timeout_seconds: int = 30
    # Whether a non-zero exit code should block the triggering action
    blocking: bool = False


# ---------------------------------------------------------------------------
# Rule / trusted-command pattern
# ---------------------------------------------------------------------------

class TrustedCommandRule(BaseModel):
    """A shell command pattern that is always approved without asking."""
    pattern: str  # glob or regex
    use_regex: bool = False
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Full BobConfig
# ---------------------------------------------------------------------------

class BobConfig(BaseModel):
    # ------------------------------------------------------------------
    # Identity / API
    # ------------------------------------------------------------------
    model: str = "gpt-5.1-codex-mini"
    api_key: Optional[str] = None
    base_url: str = "https://api.openai.com/v1"
    # Enable prompt caching (Anthropic cache_control headers)
    prompt_caching: bool = True

    # ------------------------------------------------------------------
    # Reasoning
    # ------------------------------------------------------------------
    reasoning_effort: ReasoningEffort = ReasoningEffort.MEDIUM
    reasoning_summary: ReasoningSummary = ReasoningSummary.DISABLED
    thinking_budget_tokens: int = 0  # 0 = disabled, >0 = enabled with budget

    # ------------------------------------------------------------------
    # Personality
    # ------------------------------------------------------------------
    personality: Personality = Personality.PRAGMATIC
    output_style: OutputStyle = OutputStyle.NORMAL

    # ------------------------------------------------------------------
    # Approval / safety
    # ------------------------------------------------------------------
    ask_for_approval: AskForApproval = AskForApproval.UNLESS_TRUSTED
    granular_approval: GranularApproval = Field(default_factory=GranularApproval)
    approvals_reviewer: ApprovalsReviewer = ApprovalsReviewer.USER

    # Trusted command patterns (never ask for approval)
    trusted_commands: list[TrustedCommandRule] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Sandbox
    # ------------------------------------------------------------------
    sandbox_mode: SandboxMode = SandboxMode.WORKSPACE_WRITE
    writable_roots: list[Path] = Field(default_factory=list)
    network_access: bool = False
    windows_sandbox_level: WindowsSandboxLevel = WindowsSandboxLevel.DISABLED
    # HTTP proxy URL for all outbound requests
    network_proxy: str = ""

    # ------------------------------------------------------------------
    # Collaboration / multi-agent
    # ------------------------------------------------------------------
    collaboration_mode: CollaborationMode = Field(
        default_factory=lambda: CollaborationMode(
            mode=CollaborationModeKind.DEFAULT,
            settings=CollaborationModeSettings(),
        )
    )

    # ------------------------------------------------------------------
    # Web search
    # ------------------------------------------------------------------
    web_search_mode: WebSearchMode = WebSearchMode.DISABLED
    web_search: WebSearchToolConfig = Field(default_factory=WebSearchToolConfig)

    # ------------------------------------------------------------------
    # MCP servers
    # ------------------------------------------------------------------
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    # Per-server authentication tokens for MCP
    mcp_auth_tokens: dict[str, str] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------
    hooks: list[HookConfig] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Developer / system prompt customisation
    # ------------------------------------------------------------------
    # Extra instructions appended to the system prompt
    developer_instructions: Optional[str] = None
    # Path to a markdown file whose contents are appended to the system prompt
    developer_instructions_file: Optional[Path] = None
    # Whether to include the AGENTS.md file from the workspace
    include_agents_md: bool = True

    # ------------------------------------------------------------------
    # Context / history
    # ------------------------------------------------------------------
    # Maximum number of turns to keep in the rolling context window
    max_context_turns: int = 50
    # Token threshold at which auto-compact kicks in (0 = disabled)
    auto_compact_threshold_tokens: int = 0
    # Maximum context tokens to use (0 = use model default)
    max_context_tokens: int = 0

    # ------------------------------------------------------------------
    # Service tier / billing
    # ------------------------------------------------------------------
    service_tier: Optional[ServiceTier] = None

    # ------------------------------------------------------------------
    # UI / TUI
    # ------------------------------------------------------------------
    # Disable colour output (useful for piped/scripted usage)
    no_color: bool = False
    # Color theme (dark, light, no-color)
    theme: str = "dark"
    # Suppress the welcome banner
    quiet: bool = False
    # Show token usage after each turn
    show_token_usage: bool = False
    # Show reasoning summaries in the TUI
    show_reasoning: bool = False
    # Show cost estimate after each turn
    show_cost: bool = False
    # Stream responses in real-time (False = buffer full response)
    stream_responses: bool = True

    # ------------------------------------------------------------------
    # File-change / diff
    # ------------------------------------------------------------------
    # Maximum lines of diff shown in the patch approval prompt
    patch_preview_lines: int = 20
    # Co-authored-by line appended to AI commits
    git_commit_attribution: str = ""

    # ------------------------------------------------------------------
    # Shell execution
    # ------------------------------------------------------------------
    # Default shell used for exec (None = auto-detect)
    shell: Optional[str] = None
    # Default working directory for exec (None = session cwd)
    exec_cwd: Optional[Path] = None
    # Maximum seconds a single shell command may run (0 = no limit)
    exec_timeout_seconds: int = 120

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------
    # Whether to auto-discover skills in the workspace
    enable_skills: bool = True
    # Additional skill search directories
    skill_paths: list[Path] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Memories
    # ------------------------------------------------------------------
    enable_memories: bool = True
    # Path where memories are persisted (None = ~/.bob/memories.json)
    memories_path: Optional[Path] = None

    # ------------------------------------------------------------------
    # Rollout / session persistence
    # ------------------------------------------------------------------
    # Directory for rollout storage (None = ~/.bob/rollouts)
    rollout_dir: Optional[Path] = None
    # Whether to persist session history across process restarts
    persist_sessions: bool = True

    # ------------------------------------------------------------------
    # Misc feature flags
    # ------------------------------------------------------------------
    # Enable the realtime (voice) conversation feature
    enable_realtime: bool = False
    # Enable the code review feature
    enable_review: bool = True
    # Enable background terminal tracking
    enable_background_terminals: bool = True
    # Enable guardian sub-agent for approval decisions
    enable_guardian: bool = False
    # Named feature toggles for experimental features
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    # Extra arbitrary key/value pairs forwarded to plugins / tools
    extra: dict[str, Any] = Field(default_factory=dict)
