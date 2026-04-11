from __future__ import annotations

from bob.app_server.routes._utils import parse_params
from pydantic import BaseModel


def register(router) -> None:
    async def review_submit(ctx, params: dict):
        payload = parse_params(_ReviewSubmitParams, params)
        findings = []
        if "TODO" in payload.content:
            findings.append(
                {
                    "severity": "low",
                    "message": "Found TODO marker in reviewed content.",
                    "location": payload.path,
                }
            )
        return {"decision": "comment", "findings": findings}

    async def review_result(ctx, params: dict):
        return {"status": "ok"}

    router.add("review.submit", review_submit)
    router.add("review.result", review_result)


class _ReviewSubmitParams(BaseModel):
    path: str
    content: str
