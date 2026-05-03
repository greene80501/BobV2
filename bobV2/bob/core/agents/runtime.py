from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class AgentIsolationMode(str, Enum):
    SHARED_WORKSPACE = "shared_workspace"
    GIT_WORKTREE = "git_worktree"


class AgentPermissionMode(str, Enum):
    FULL_AUTO = "full_auto"
    READ_ONLY = "read_only"


class AgentDefinition(BaseModel):
    name: str
    description: str = ""
    instructions: str = ""
    model: Optional[str] = None
    allowed_tools: list[str] = Field(default_factory=list)
    fork_mode: str = "none"
    isolation_mode: AgentIsolationMode = AgentIsolationMode.SHARED_WORKSPACE
    permission_mode: AgentPermissionMode = AgentPermissionMode.FULL_AUTO
    source: str = "builtin"
    path: Optional[Path] = None

    @model_validator(mode="after")
    def _validate_fork_mode(self) -> "AgentDefinition":
        mode = (self.fork_mode or "none").strip()
        if mode in {"none", "all"}:
            return self
        if mode.startswith("last_n:"):
            try:
                n = int(mode.split(":", 1)[1])
            except ValueError as exc:
                raise ValueError("fork_mode last_n must use an integer suffix") from exc
            if n <= 0:
                raise ValueError("fork_mode last_n must be greater than zero")
            return self
        raise ValueError("fork_mode must be one of: none, all, last_n:N")
