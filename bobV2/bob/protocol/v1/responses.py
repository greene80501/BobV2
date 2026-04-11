from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from bob.protocol.v1.common import PROTOCOL_VERSION


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ServerCapabilitiesResult(BaseModel):
    server_name: str = "bob"
    protocol_version: str = PROTOCOL_VERSION
    supported_protocol_versions: list[str] = Field(default_factory=lambda: [PROTOCOL_VERSION])
    methods: list[str] = Field(default_factory=list)
    legacy_methods: list[str] = Field(default_factory=list)
    features: dict[str, bool] = Field(default_factory=dict)


class ThreadObject(BaseModel):
    id: str
    status: Literal["running", "closed"] = "running"
    model: str
    cwd: str
    created_at_ts: int
    updated_at_ts: int
    name: Optional[str] = None


class TurnObject(BaseModel):
    id: str
    thread_id: str
    state: Literal["queued", "running", "completed", "interrupted", "failed", "cancelled"]
    created_at_ts: int
    updated_at_ts: int
    submission_id: Optional[str] = None
    turn_id: Optional[str] = None
    output_text: str = ""
    error: Optional[str] = None


class CommandObject(BaseModel):
    id: str
    thread_id: str
    state: Literal["running", "completed", "failed", "cancelled"]
    created_at_ts: int
    updated_at_ts: int
    command: str
    exit_code: Optional[int] = None


class TaskObject(BaseModel):
    id: str
    type: str
    status: str
    priority: str
    created_at_ts: int
    updated_at_ts: int
    payload: dict[str, Any] = Field(default_factory=dict)
    result: Optional[dict[str, Any]] = None

