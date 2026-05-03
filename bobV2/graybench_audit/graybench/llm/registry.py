"""Provider factory – resolves provider/model/route to an LLMProvider instance."""

import logging
from typing import Optional

from ..db import api_keys as keys_db
from ..db import models_db
from .base import LLMProvider

log = logging.getLogger(__name__)

# Provider class imports (lazy to avoid import errors if SDK missing)
_PROVIDER_MAP = {
    "google": "graybench.llm.google_provider:GoogleProvider",
    "openai": "graybench.llm.openai_provider:OpenAIProvider",
    "anthropic": "graybench.llm.anthropic_provider:AnthropicProvider",
    "deepseek": "graybench.llm.deepseek_provider:DeepSeekProvider",
    "moonshot": "graybench.llm.moonshot_provider:MoonshotProvider",
    "openrouter": "graybench.llm.openrouter_provider:OpenRouterProvider",
    "graygate": "graybench.llm.graygate_provider:GrayGateProvider",
}


def _import_class(dotted_path: str):
    """Import a class from a dotted module:Class path."""
    module_path, class_name = dotted_path.rsplit(":", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def get_provider(
    model_string: str,
    route: str = "direct",
    api_key: Optional[str] = None,
    max_tokens: int = 8192,
    temperature: float = 0.0,
    reasoning: bool = False,
) -> LLMProvider:
    """Create an LLM provider instance.

    Args:
        model_string: 'provider/model_id' (e.g., 'google/gemini-3-flash-preview')
        route: 'direct' or 'openrouter'
        api_key: Explicit API key (overrides env/DB lookup)
        max_tokens: Default max output tokens
        temperature: Default temperature
        reasoning: Enable reasoning mode (OpenRouter)

    Returns:
        An LLMProvider instance ready to use.
    """
    # Parse provider and model_id
    if "/" in model_string:
        provider, model_id = model_string.split("/", 1)
    else:
        # Try to find the model in DB
        model_info = models_db.find_model(model_string)
        if model_info:
            provider = model_info["provider"]
            model_id = model_info["model_id"]
        else:
            raise ValueError(
                f"Cannot resolve model '{model_string}'. "
                f"Use 'provider/model_id' format (e.g., 'google/gemini-3-flash-preview')."
            )

    # Route through OpenRouter if requested
    if route == "openrouter":
        key = api_key or keys_db.get_key("openrouter")
        if not key:
            raise ValueError(
                "OpenRouter API key required. Set OPENROUTER_API_KEY or run: "
                "graybench keys set openrouter"
            )
        # Use the OpenRouter model path (check DB for openrouter_id)
        model_info = models_db.get_model(provider, model_id)
        or_model = model_string  # Default: provider/model_id
        if model_info and model_info.get("openrouter_id"):
            or_model = model_info["openrouter_id"]

        OpenRouterProvider = _import_class(_PROVIDER_MAP["openrouter"])

        # Auto-detect reasoning for known reasoning models
        if not reasoning and model_info and model_info.get("supports_reasoning"):
            reasoning = True

        return OpenRouterProvider(
            api_key=key,
            model=or_model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning=reasoning,
        )

    # Direct provider
    if provider == "graygate":
        GrayGateProvider = _import_class(_PROVIDER_MAP["graygate"])
        return GrayGateProvider()

    if provider not in _PROVIDER_MAP:
        raise ValueError(
            f"Unknown provider '{provider}'. "
            f"Available: {', '.join(sorted(_PROVIDER_MAP.keys()))}"
        )

    # Resolve API key
    key = api_key or keys_db.get_key(provider)
    if not key:
        raise ValueError(
            f"API key required for {provider}. "
            f"Set the environment variable or run: graybench keys set {provider}"
        )

    ProviderClass = _import_class(_PROVIDER_MAP[provider])
    return ProviderClass(
        api_key=key,
        model=model_id,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def list_providers() -> list[str]:
    """List all available provider names."""
    return sorted(_PROVIDER_MAP.keys())
