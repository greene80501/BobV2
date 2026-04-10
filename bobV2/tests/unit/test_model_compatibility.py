from __future__ import annotations

from bob.config.schema import BobConfig
from bob.llm.compatibility import (
    ClientRoute,
    build_model_request_params,
    get_model_compatibility,
    get_picker_seed_models,
    resolve_provider_auth,
)
from bob.protocol.config_types import ReasoningEffort, ServiceTier


def test_openai_responses_models_use_native_route() -> None:
    compat = get_model_compatibility("gpt-5.1-codex-mini")

    assert compat.provider == "openai"
    assert compat.route == ClientRoute.OPENAI_RESPONSES
    assert compat.canonical_model == "gpt-5.1-codex-mini"


def test_bare_gemini_model_is_normalized_to_gemini_provider() -> None:
    compat = get_model_compatibility("gemini-2.5-pro")

    assert compat.provider == "gemini"
    assert compat.route == ClientRoute.LITELLM_CHAT
    assert compat.canonical_model == "gemini/gemini-2.5-pro"
    assert any("gemini/" in note for note in compat.notes)


def test_provider_specific_auth_beats_global_fallback() -> None:
    config = BobConfig.model_validate(
        {
            "model": "anthropic/claude-3.5-sonnet",
            "api_key": "global-key",
            "providers": {
                "anthropic": {
                    "api_key": "anthropic-key",
                    "base_url": "https://anthropic.example/v1",
                }
            },
        }
    )

    resolved = resolve_provider_auth("anthropic/claude-3.5-sonnet", config, env={})

    assert resolved.provider == "anthropic"
    assert resolved.api_key == "anthropic-key"
    assert resolved.base_url == "https://anthropic.example/v1"
    assert resolved.used_global_fallback is False
    assert resolved.missing == ()


def test_vertex_ai_requires_location_and_credentials() -> None:
    config = BobConfig.model_validate(
        {
            "model": "vertex_ai/gemini-2.5-pro",
            "providers": {
                "vertex_ai": {
                    "project": "demo-project",
                }
            },
        }
    )

    resolved = resolve_provider_auth("vertex_ai/gemini-2.5-pro", config, env={})

    assert resolved.provider == "vertex_ai"
    assert "VERTEXAI_LOCATION" in resolved.missing
    assert "GOOGLE_APPLICATION_CREDENTIALS" in resolved.missing


def test_openai_request_params_map_reasoning_and_service_tier() -> None:
    config = BobConfig(
        model="gpt-5.1-codex-mini",
        reasoning_effort=ReasoningEffort.HIGH,
        service_tier=ServiceTier.PRO,
    )
    compat = get_model_compatibility(config.model)

    params = build_model_request_params(config, compat)

    assert params == {
        "reasoning": {"effort": "high"},
        "service_tier": "pro",
    }


def test_anthropic_request_params_map_caching_and_thinking_budget() -> None:
    config = BobConfig(
        model="anthropic/claude-3.5-sonnet",
        prompt_caching=True,
        thinking_budget_tokens=2048,
    )
    compat = get_model_compatibility(config.model)

    params = build_model_request_params(config, compat)

    assert params["prompt_caching"] is True
    assert params["thinking"] == {"type": "enabled", "budget_tokens": 2048}


def test_gemini_request_params_map_reasoning_effort() -> None:
    config = BobConfig(
        model="gemini/gemini-2.5-pro",
        reasoning_effort=ReasoningEffort.LOW,
        service_tier=ServiceTier.TEAM_OR_ENTERPRISE,
    )
    compat = get_model_compatibility(config.model)

    params = build_model_request_params(config, compat)

    assert params["reasoning_effort"] == "low"
    assert params["service_tier"] == "team_or_enterprise"


def test_picker_seeds_include_anthropic_and_gemini() -> None:
    model_ids = {row["model_id"] for row in get_picker_seed_models()}

    assert any(model_id.startswith("anthropic/claude") for model_id in model_ids)
    assert any(model_id.startswith("gemini/gemini") for model_id in model_ids)
