from __future__ import annotations

from pathlib import Path

from bob.app_server.routes._utils import parse_params
from bob.protocol.v1.requests import FilesGlobParams, FilesGrepParams, FilesReadParams, FilesWriteParams


def _resolve(path: str, root: str | None = None) -> Path:
    if root:
        return (Path(root).resolve() / path).resolve()
    return Path(path).resolve()


def register(router) -> None:
    async def files_read(ctx, params: dict):
        p = parse_params(FilesReadParams, params)
        path = _resolve(p.path)
        return {"path": str(path), "content": path.read_text(encoding="utf-8")}

    async def files_write(ctx, params: dict):
        p = parse_params(FilesWriteParams, params)
        path = _resolve(p.path)
        if p.create_parents:
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(p.content, encoding="utf-8")
        return {"path": str(path), "bytes_written": len(p.content.encode("utf-8"))}

    async def files_edit(ctx, params: dict):
        path = _resolve(str(params.get("path", "")))
        old = str(params.get("old", ""))
        new = str(params.get("new", ""))
        content = path.read_text(encoding="utf-8")
        count = content.count(old)
        if count:
            content = content.replace(old, new)
            path.write_text(content, encoding="utf-8")
        return {"path": str(path), "replacements": count}

    async def files_glob(ctx, params: dict):
        p = parse_params(FilesGlobParams, params)
        root = Path(p.root).resolve() if p.root else Path.cwd()
        matches = [str(x) for x in root.rglob(p.pattern)]
        return {"matches": matches[:2000]}

    async def files_grep(ctx, params: dict):
        p = parse_params(FilesGrepParams, params)
        root = Path(p.root).resolve() if p.root else Path.cwd()
        needle = p.pattern if p.case_sensitive else p.pattern.lower()
        hits: list[dict] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            haystack = text if p.case_sensitive else text.lower()
            if needle in haystack:
                hits.append({"path": str(path)})
            if len(hits) >= 1000:
                break
        return {"matches": hits}

    router.add("files.read", files_read)
    router.add("files.write", files_write)
    router.add("files.edit", files_edit)
    router.add("files.glob", files_glob)
    router.add("files.grep", files_grep)

