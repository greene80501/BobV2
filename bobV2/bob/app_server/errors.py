from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppServerError(Exception):
    code: int
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_jsonrpc(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data:
            payload["data"] = self.data
        return payload


def invalid_params(message: str, **data: Any) -> AppServerError:
    return AppServerError(-32602, message, data)


def not_found(message: str, **data: Any) -> AppServerError:
    return AppServerError(-32004, message, data)


def unauthorized(message: str = "Unauthorized") -> AppServerError:
    return AppServerError(-32001, message)

