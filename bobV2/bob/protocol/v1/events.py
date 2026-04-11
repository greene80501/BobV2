from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RealtimeEventEnvelope(BaseModel):
    type: Literal["realtime.event"] = "realtime.event"
    subscription_id: str
    cursor: int
    channels: list[str] = Field(default_factory=list)
    event: dict[str, Any]


class RealtimeHeartbeatEvent(BaseModel):
    type: Literal["realtime.heartbeat"] = "realtime.heartbeat"
    connection_id: str
    ts_ms: int

