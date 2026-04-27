from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ConnectionContext:
    id: str
    ws: Any = None
    subscriptions: dict[str, Any] = field(default_factory=dict)
    forwarder_tasks: dict[str, Any] = field(default_factory=dict)


@dataclass
class RequestContext:
    registry: Any
    event_bus: Any
    task_runtime: Any
    router: Any
    connection: Optional[ConnectionContext] = None
    logger: Any = None
