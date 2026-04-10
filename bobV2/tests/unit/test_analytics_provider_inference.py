from __future__ import annotations

from bob.analytics.tracker import _infer_provider


def test_prefixed_gemini_provider_is_reported_consistently() -> None:
    assert _infer_provider("gemini/gemini-2.5-pro") == "gemini"


def test_prefixed_anthropic_provider_is_reported_consistently() -> None:
    assert _infer_provider("anthropic/claude-3.5-sonnet") == "anthropic"


def test_catalog_backed_glm_provider_uses_matrix_name() -> None:
    assert _infer_provider("glm-4.5") == "glm_zai"
