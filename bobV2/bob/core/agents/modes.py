from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CollaborationMode:
    name: str
    template: Optional[str]
    max_agents: int
    max_runtime_seconds: int


MODES: dict[str, CollaborationMode] = {
    "default": CollaborationMode("default", None, 8, 1800),
    "planner": CollaborationMode("planner", "plan", 4, 1200),
    "implementer": CollaborationMode("implementer", "write", 8, 2400),
    "reviewer": CollaborationMode("reviewer", "review", 4, 1200),
    "verifier": CollaborationMode("verifier", "verify", 4, 1200),
}

