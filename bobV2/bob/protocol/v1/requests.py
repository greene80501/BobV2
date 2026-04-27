from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class RpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: Optional[str | int] = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    protocol_version: Optional[str] = None


class ServerCapabilitiesParams(BaseModel):
    protocol_version: Optional[str] = None


class ThreadsCreateParams(BaseModel):
    cwd: Optional[str] = None
    model: Optional[str] = None
    name: Optional[str] = None
    ephemeral: bool = False


class ThreadsGetParams(BaseModel):
    thread_id: str


class ThreadsListParams(BaseModel):
    limit: int = 25
    offset: int = 0
    cwd: Optional[str] = None


class TurnsSubmitParams(BaseModel):
    thread_id: str
    items: list[dict[str, Any]]
    developer_message_override: Optional[str] = None


class TurnsGetParams(BaseModel):
    thread_id: str
    turn_id: str


class TurnsListParams(BaseModel):
    thread_id: str
    limit: int = 50


class TurnsInterruptParams(BaseModel):
    thread_id: str
    graceful: bool = True


class TurnsCancelParams(BaseModel):
    thread_id: str


class HistoryReadParams(BaseModel):
    thread_id: str
    limit: int = 200


class FilesReadParams(BaseModel):
    path: str


class FilesWriteParams(BaseModel):
    path: str
    content: str
    create_parents: bool = True


class FilesGlobParams(BaseModel):
    pattern: str
    root: Optional[str] = None


class FilesGrepParams(BaseModel):
    pattern: str
    root: Optional[str] = None
    case_sensitive: bool = False


class ExecStartParams(BaseModel):
    thread_id: str
    command: str
    cwd: Optional[str] = None
    background: bool = False


class ExecWaitParams(BaseModel):
    thread_id: str
    command_id: str
    timeout_ms: int = 30000


class ExecTerminateParams(BaseModel):
    thread_id: str
    command_id: str


class DynamicToolDescriptor(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    source: str = "dynamic"
    expose_to_model: bool = False
    discoverable: bool = True
    is_mutating: bool = True
    supports_parallel: bool = False
    requires_network_approval: bool = False
    keywords: list[str] = Field(default_factory=list)
    deferred: bool = False
    timeout_seconds: float = 120.0
    max_retries: int = 1
    max_output_chars: int = 32000


class DynamicToolsRegisterParams(BaseModel):
    thread_id: str
    tools: list[DynamicToolDescriptor] = Field(default_factory=list)


class DynamicToolsListParams(BaseModel):
    thread_id: str
    include_hidden: bool = True
    source: Optional[str] = None


class DynamicToolsSearchParams(BaseModel):
    thread_id: str
    query: str = ""
    limit: int = 20
    include_hidden: bool = True
    sources: list[str] = Field(default_factory=list)
    auto_enable: bool = False


class DynamicToolsEnableParams(BaseModel):
    thread_id: str
    tool_names: list[str] = Field(default_factory=list)
    expose_to_model: bool = True


class DynamicToolsRespondParams(BaseModel):
    thread_id: str
    tool_call_id: str
    result: Any


class TasksCreateParams(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: str = "medium"
    max_attempts: int = 3
    timeout_seconds: int = 900
    run_at_ts: Optional[int] = None


class TasksGetParams(BaseModel):
    task_id: str


class TasksListParams(BaseModel):
    status: Optional[str] = None
    limit: int = 100


class TasksCancelParams(BaseModel):
    task_id: str


class RealtimeSubscribeParams(BaseModel):
    channels: list[str] = Field(default_factory=list)
    after_cursor: Optional[int] = None


class RealtimeUnsubscribeParams(BaseModel):
    subscription_id: str


class RealtimeReplayParams(BaseModel):
    channels: list[str] = Field(default_factory=list)
    after_cursor: Optional[int] = None
    limit: int = 200
