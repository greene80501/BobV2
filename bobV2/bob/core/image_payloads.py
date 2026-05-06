from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from bob.core.session import BobSession

from bob.core.context_budget import compute_context_budget

ImageDetailLevel = Literal["low", "medium", "high"]

_DETAIL_ORDER: tuple[ImageDetailLevel, ...] = ("high", "medium", "low")
_DETAIL_TO_PROVIDER_DETAIL = {
    "low": "low",
    "medium": "auto",
    "high": "high",
}
_DETAIL_PROFILES: dict[ImageDetailLevel, dict[str, int]] = {
    "low": {"max_dim": 512, "quality": 50, "max_chars": 60_000},
    "medium": {"max_dim": 1024, "quality": 70, "max_chars": 120_000},
    "high": {"max_dim": 1600, "quality": 85, "max_chars": 200_000},
}
_HIGH_DETAIL_HINTS = (
    "design",
    "diagram",
    "graph",
    "image",
    "layout",
    "look",
    "ocr",
    "photo",
    "read text",
    "screenshot",
    "see",
    "ui",
    "visual",
)


@dataclass(frozen=True)
class PreparedImagePayload:
    data_url: str
    mime: str
    detail_level: ImageDetailLevel
    approx_tokens: int
    byte_size: int

    @property
    def provider_detail(self) -> str:
        return _DETAIL_TO_PROVIDER_DETAIL[self.detail_level]


def select_image_detail_level(
    *,
    session: Optional["BobSession"] = None,
    prompt_text: str = "",
    requested: Optional[str] = None,
) -> ImageDetailLevel:
    if requested in _DETAIL_PROFILES:
        return requested  # type: ignore[return-value]

    pressure = 0.0
    if session is not None:
        try:
            current_tokens = max(0, int(session.context_manager.approx_token_count()))
            trigger_tokens = max(1, int(compute_context_budget(session).compact_trigger_tokens))
            pressure = current_tokens / trigger_tokens
        except Exception:
            pressure = 0.0

    if pressure >= 0.95:
        return "low"
    if pressure >= 0.75:
        return "medium"

    prompt_norm = prompt_text.lower()
    if any(hint in prompt_norm for hint in _HIGH_DETAIL_HINTS) and pressure < 0.55:
        return "high"

    return "medium"


def prepare_local_image_for_model(
    path: Path,
    *,
    mime_hint: str,
    session: Optional["BobSession"] = None,
    prompt_text: str = "",
    requested: Optional[str] = None,
) -> PreparedImagePayload:
    raw = path.read_bytes()
    detail_level = select_image_detail_level(
        session=session,
        prompt_text=prompt_text,
        requested=requested,
    )
    return _prepare_raster_payload(
        raw,
        mime_hint=mime_hint,
        preferred_detail=detail_level,
    )


def prepare_base64_image_for_model(
    raw: str,
    *,
    mime_hint: str = "image/jpeg",
    session: Optional["BobSession"] = None,
    prompt_text: str = "",
    requested: Optional[str] = None,
) -> PreparedImagePayload:
    b64 = raw.split(",", 1)[1] if "," in raw else raw
    padding = (-len(b64)) % 4
    if padding:
        b64 += "=" * padding
    decoded = base64.b64decode(b64)
    detail_level = select_image_detail_level(
        session=session,
        prompt_text=prompt_text,
        requested=requested,
    )
    return _prepare_raster_payload(
        decoded,
        mime_hint=mime_hint,
        preferred_detail=detail_level,
    )


def _prepare_raster_payload(
    raw: bytes,
    *,
    mime_hint: str,
    preferred_detail: ImageDetailLevel,
) -> PreparedImagePayload:
    preferred_index = _DETAIL_ORDER.index(preferred_detail)
    candidate_levels = _DETAIL_ORDER[preferred_index:] or (preferred_detail,)

    for detail_level in candidate_levels:
        payload = _render_payload(raw, mime_hint=mime_hint, detail_level=detail_level)
        max_chars = _DETAIL_PROFILES[detail_level]["max_chars"]
        if len(payload.data_url) <= max_chars:
            return payload

    return _render_payload(raw, mime_hint=mime_hint, detail_level="low")


def _render_payload(
    raw: bytes,
    *,
    mime_hint: str,
    detail_level: ImageDetailLevel,
) -> PreparedImagePayload:
    rendered_mime = mime_hint
    rendered_bytes = raw

    try:
        from PIL import Image as _Image  # type: ignore[import]

        profile = _DETAIL_PROFILES[detail_level]
        img = _Image.open(io.BytesIO(raw))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        width, height = img.size
        max_dim = profile["max_dim"]
        largest_dim = max(width, height)
        if largest_dim > max_dim:
            ratio = max_dim / largest_dim
            img = img.resize(
                (max(1, int(width * ratio)), max(1, int(height * ratio))),
                _Image.LANCZOS,
            )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=profile["quality"], optimize=True)
        rendered_bytes = buf.getvalue()
        rendered_mime = "image/jpeg"
    except Exception:
        rendered_mime = mime_hint
        rendered_bytes = raw

    b64 = base64.b64encode(rendered_bytes).decode("ascii")
    return PreparedImagePayload(
        data_url=f"data:{rendered_mime};base64,{b64}",
        mime=rendered_mime,
        detail_level=detail_level,
        approx_tokens=len(b64) // 4,
        byte_size=len(rendered_bytes),
    )
