from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TaskComplexity(str, Enum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class SwarmPhase(str, Enum):
    EXPLORATION = "exploration"
    PLANNING = "planning"
    AWAITING_AUTHORIZATION = "awaiting_authorization"
    EXECUTION = "execution"
    AGGREGATION = "aggregation"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SwarmTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:6])
    role: str  # implementer | tester | reviewer | verifier | explorer
    task: str
    deps: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    files_to_read: list[str] = Field(default_factory=list)
    files_to_modify: list[str] = Field(default_factory=list)
    tools_needed: list[str] = Field(default_factory=list)
    estimated_turns: int = 10
    # mutable state tracked during execution
    status: str = "pending"
    agent_id: Optional[str] = None
    result: Optional[str] = None
    workspace_dir: Optional[str] = None


class SwarmPlan(BaseModel):
    run_id: str
    original_task: str
    tasks: list[SwarmTask]
    total_agents: int
    planner_status: str = "planned"  # planned | fallback
    planner_error: str = ""
    planner_attempts: int = 1
    executable: bool = True
    affected_files: list[str] = Field(default_factory=list)
    risk_summary: str = ""
    estimated_changes: str = ""
    exploration_findings: str = ""

    @property
    def has_high_risk(self) -> bool:
        return any(t.risk_level == RiskLevel.HIGH for t in self.tasks)

    @property
    def execution_tasks(self) -> list[SwarmTask]:
        return [t for t in self.tasks if t.role not in ("explorer", "researcher")]

    @property
    def exploration_tasks(self) -> list[SwarmTask]:
        return [t for t in self.tasks if t.role in ("explorer", "researcher")]


class SwarmRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    task: str
    phase: SwarmPhase = SwarmPhase.EXPLORATION
    plan: Optional[SwarmPlan] = None
    started_at: float = 0.0
    completed_at: Optional[float] = None
    success: Optional[bool] = None
    patch_text: Optional[str] = None
    files_changed: list[str] = Field(default_factory=list)
    audit_path: Optional[str] = None
