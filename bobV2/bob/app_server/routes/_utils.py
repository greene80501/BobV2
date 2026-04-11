from __future__ import annotations

from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from bob.app_server.errors import invalid_params

T = TypeVar("T", bound=BaseModel)


def parse_params(model: Type[T], raw: dict) -> T:
    try:
        return model.model_validate(raw or {})
    except ValidationError as exc:
        raise invalid_params("Invalid params", validation_error=exc.errors()) from exc

