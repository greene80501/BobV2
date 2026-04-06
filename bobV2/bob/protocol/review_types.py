from __future__ import annotations
from typing import Optional
from pydantic import BaseModel
from pathlib import Path


class ReviewLineRange(BaseModel):
    start: int
    end: int


class ReviewCodeLocation(BaseModel):
    absolute_file_path: Path
    line_range: ReviewLineRange


class ReviewFinding(BaseModel):
    title: str
    body: str
    confidence_score: float  # 0.0-1.0
    priority: int
    code_location: ReviewCodeLocation


class ReviewOutputEvent(BaseModel):
    findings: list[ReviewFinding]
    overall_correctness: str
    overall_explanation: str
    overall_confidence_score: float


class ReviewRequest(BaseModel):
    target_kind: str  # "uncommitted_changes" | "base_branch" | "commit" | "custom"
    branch: Optional[str] = None
    sha: Optional[str] = None
    title: Optional[str] = None
    instructions: Optional[str] = None
    user_facing_hint: Optional[str] = None
