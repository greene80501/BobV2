from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class JsonRpcRequest(BaseModel):
    jsonrpc: str
    method: str
    id: Optional[str | int] = None
    params: dict[str, Any] = Field(default_factory=dict)
    protocol_version: Optional[str] = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[str | int] = None
    result: Optional[Any] = None
    error: Optional[dict[str, Any]] = None

