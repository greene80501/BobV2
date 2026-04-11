from __future__ import annotations

import json
from pathlib import Path
from typing import Type

from pydantic import BaseModel

from bob.protocol.v1 import events, requests, responses


def _iter_models(module) -> list[Type[BaseModel]]:
    out: list[Type[BaseModel]] = []
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel:
            out.append(obj)
    out.sort(key=lambda m: m.__name__)
    return out


def export_jsonschemas(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for module in (requests, responses, events):
        for model in _iter_models(module):
            data = model.model_json_schema()
            target = output_dir / f"{module.__name__.split('.')[-1]}.{model.__name__}.json"
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")
            files.append(target)
    return files


def main() -> None:
    root = Path(__file__).resolve().parent
    out = export_jsonschemas(root / "schemas")
    print(f"Exported {len(out)} schema files to {root / 'schemas'}")


if __name__ == "__main__":
    main()

