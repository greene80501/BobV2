from __future__ import annotations
from typing import Optional
from pydantic import BaseModel
from bob.protocol.config_types import StepStatus


class PlanItemArg(BaseModel):
    step: str
    status: StepStatus


class UpdatePlanArgs(BaseModel):
    explanation: Optional[str] = None
    plan: list[PlanItemArg]
