from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Optional


class SupportLevel(str, Enum):
    STABLE = "stable"
    EXPERIMENTAL = "experimental"
    CATALOG_ONLY = "catalog_only"
    UNKNOWN = "unknown"


class ClientRoute(str, Enum):
    OPENAI_RESPONSES = "openai_responses"
    LITELLM_CHAT = "litellm_chat"


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    display_name: str
    support_level: SupportLevel
    route: ClientRoute
    api_key_env_vars: tuple[str, ...] = ()
    base_url_env_vars: tuple[str, ...] = ()
    env_field_map: dict[str, str] = field(default_factory=dict)
    provider_kwargs_map: dict[str, str] = field(default_factory=dict)
    suggested_models: tuple[str, ...] = ()
    supports_reasoning_effort: bool = False
    supports_thinking_budget: bool = False
    supports_prompt_caching: bool = False
    supports_vision: bool = False
    supports_service_tier: bool = False
    notes: str = ""


@dataclass(frozen=True)
class ModelCompatibility:
    requested_model: str
    canonical_model: str
    bare_model: str
    provider: str
    route: ClientRoute
    support_level: SupportLevel
    supports_reasoning_effort: bool
    supports_thinking_budget: bool
    supports_prompt_caching: bool
    supports_vision: bool
    supports_service_tier: bool
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedProviderAuth:
    provider: str
    api_key: str = ""
    base_url: Optional[str] = None
    provider_kwargs: dict[str, Any] = field(default_factory=dict)
    env_overrides: dict[str, str] = field(default_factory=dict)
    missing: tuple[str, ...] = ()
    used_global_fallback: bool = False


_PROVIDER_ALIASES: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "google_ai_studio": "gemini",
    "vertex_ai": "vertex_ai",
    "azure": "azure",
    "groq": "groq",
    "mistral": "mistral",
    "cohere": "cohere",
    "together_ai": "together_ai",
    "openrouter": "openrouter",
    "xai": "xai",
    "ibm_watsonx": "ibm_watsonx",
    "glm_zai": "glm_zai",
    "ollama": "ollama",
}


_PREFIX_PROVIDER_MAP: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "vertex_ai": "vertex_ai",
    "azure": "azure",
    "groq": "groq",
    "mistral": "mistral",
    "cohere": "cohere",
    "together_ai": "together_ai",
    "openrouter": "openrouter",
    "xai": "xai",
    "ollama": "ollama",
}


_MODEL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"),
    ("gemini", "gemini"),
    ("grok", "xai"),
    ("glm-", "glm_zai"),
    ("command-", "cohere"),
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("text-", "openai"),
    ("codex", "openai"),
)


_OPENAI_RESPONSES_PREFIXES: tuple[str, ...] = (
    "gpt-5",
    "o1",
    "o3",
    "o4",
    "codex",
)


_PROFILES: dict[str, ProviderProfile] = {
    "openai": ProviderProfile(
        name="openai",
        display_name="OpenAI",
        support_level=SupportLevel.STABLE,
        route=ClientRoute.LITELLM_CHAT,
        api_key_env_vars=("OPENAI_API_KEY",),
        base_url_env_vars=("OPENAI_API_BASE",),
        provider_kwargs_map={"organization": "organization"},
        suggested_models=(
            "gpt-5.1-codex-mini",
            "gpt-5.3-codex",
            "gpt-5",
            "gpt-5-mini",
            "gpt-4o",
        ),
        supports_reasoning_effort=True,
        supports_service_tier=True,
        supports_vision=True,
        notes="GPT-5/o-series/codex are routed through OpenAI's native Responses API. Other OpenAI models use LiteLLM chat.",
    ),
    "anthropic": ProviderProfile(
        name="anthropic",
        display_name="Anthropic",
        support_level=SupportLevel.STABLE,
        route=ClientRoute.LITELLM_CHAT,
        api_key_env_vars=("ANTHROPIC_API_KEY",),
        suggested_models=(
            "anthropic/claude-3.5-sonnet",
            "anthropic/claude-3.5-haiku",
            "anthropic/claude-3.7-sonnet",
        ),
        supports_thinking_budget=True,
        supports_prompt_caching=True,
        notes="LiteLLM uses the anthropic/ provider route with ANTHROPIC_API_KEY.",
    ),
    "gemini": ProviderProfile(
        name="gemini",
        display_name="Google Gemini",
        support_level=SupportLevel.STABLE,
        route=ClientRoute.LITELLM_CHAT,
        api_key_env_vars=("GEMINI_API_KEY",),
        suggested_models=(
            "gemini/gemini-2.5-pro",
            "gemini/gemini-2.5-flash",
        ),
        supports_reasoning_effort=True,
        supports_thinking_budget=True,
        supports_vision=True,
        supports_service_tier=True,
        notes="Google AI Studio route with GEMINI_API_KEY. Bob normalizes bare gemini-* names to gemini/<model>.",
    ),
    "vertex_ai": ProviderProfile(
        name="vertex_ai",
        display_name="Google Gemini (Vertex AI)",
        support_level=SupportLevel.STABLE,
        route=ClientRoute.LITELLM_CHAT,
        env_field_map={
            "project": "VERTEXAI_PROJECT",
            "location": "VERTEXAI_LOCATION",
            "credentials_path": "GOOGLE_APPLICATION_CREDENTIALS",
        },
        suggested_models=(
            "vertex_ai/gemini-2.5-pro",
            "vertex_ai/gemini-2.5-flash",
        ),
        supports_vision=True,
        notes="Vertex AI route. Requires VERTEXAI_LOCATION plus GCP credentials; VERTEXAI_PROJECT is optional.",
    ),
    "azure": ProviderProfile(
        name="azure",
        display_name="Azure OpenAI",
        support_level=SupportLevel.EXPERIMENTAL,
        route=ClientRoute.LITELLM_CHAT,
        api_key_env_vars=("AZURE_API_KEY",),
        base_url_env_vars=("AZURE_API_BASE",),
        provider_kwargs_map={"api_version": "api_version"},
        suggested_models=("azure/<deployment_name>",),
        supports_service_tier=True,
        notes="LiteLLM Azure path using deployment-name models and Azure-specific config.",
    ),
    "groq": ProviderProfile(
        name="groq",
        display_name="Groq",
        support_level=SupportLevel.EXPERIMENTAL,
        route=ClientRoute.LITELLM_CHAT,
        api_key_env_vars=("GROQ_API_KEY",),
        suggested_models=("groq/llama-3.3-70b-versatile",),
        notes="Experimental Groq path through LiteLLM.",
    ),
    "mistral": ProviderProfile(
        name="mistral",
        display_name="Mistral",
        support_level=SupportLevel.EXPERIMENTAL,
        route=ClientRoute.LITELLM_CHAT,
        api_key_env_vars=("MISTRAL_API_KEY",),
        suggested_models=("mistral/mistral-large-latest",),
        supports_vision=True,
        notes="Experimental Mistral API path through LiteLLM.",
    ),
    "cohere": ProviderProfile(
        name="cohere",
        display_name="Cohere",
        support_level=SupportLevel.EXPERIMENTAL,
        route=ClientRoute.LITELLM_CHAT,
        api_key_env_vars=("COHERE_API_KEY",),
        suggested_models=("cohere/command-r-plus",),
        notes="Experimental Cohere path through LiteLLM.",
    ),
    "together_ai": ProviderProfile(
        name="together_ai",
        display_name="Together AI",
        support_level=SupportLevel.EXPERIMENTAL,
        route=ClientRoute.LITELLM_CHAT,
        api_key_env_vars=("TOGETHERAI_API_KEY", "TOGETHER_API_KEY"),
        suggested_models=("together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",),
        notes="Experimental Together AI path through LiteLLM.",
    ),
    "openrouter": ProviderProfile(
        name="openrouter",
        display_name="OpenRouter",
        support_level=SupportLevel.EXPERIMENTAL,
        route=ClientRoute.LITELLM_CHAT,
        api_key_env_vars=("OPENROUTER_API_KEY",),
        suggested_models=("openrouter/openai/gpt-4o",),
        supports_vision=True,
        notes="Experimental multi-provider gateway path through LiteLLM.",
    ),
    "xai": ProviderProfile(
        name="xai",
        display_name="xAI",
        support_level=SupportLevel.EXPERIMENTAL,
        route=ClientRoute.LITELLM_CHAT,
        api_key_env_vars=("XAI_API_KEY",),
        suggested_models=("xai/grok-2-latest",),
        notes="Experimental xAI path through LiteLLM.",
    ),
    "ibm_watsonx": ProviderProfile(
        name="ibm_watsonx",
        display_name="IBM watsonx",
        support_level=SupportLevel.CATALOG_ONLY,
        route=ClientRoute.LITELLM_CHAT,
        suggested_models=("ibm/granite-3-8b-instruct",),
        supports_vision=True,
        notes="Catalog-backed best-effort provider. Configure auth under [providers.ibm_watsonx].",
    ),
    "glm_zai": ProviderProfile(
        name="glm_zai",
        display_name="GLM ZAI",
        support_level=SupportLevel.CATALOG_ONLY,
        route=ClientRoute.LITELLM_CHAT,
        suggested_models=("glm-4.5",),
        supports_vision=True,
        notes="Catalog-backed best-effort provider. Configure auth under [providers.glm_zai].",
    ),
    "ollama": ProviderProfile(
        name="ollama",
        display_name="Ollama",
        support_level=SupportLevel.EXPERIMENTAL,
        route=ClientRoute.LITELLM_CHAT,
        base_url_env_vars=("OLLAMA_API_BASE",),
        suggested_models=("ollama/llama3.1",),
        notes="Experimental local-model path through LiteLLM.",
    ),
    "unknown": ProviderProfile(
        name="unknown",
        display_name="Unknown",
        support_level=SupportLevel.UNKNOWN,
        route=ClientRoute.LITELLM_CHAT,
        notes="Unknown model/provider; Bob will use LiteLLM as a best-effort fallback.",
    ),
}


def get_provider_profile(provider: str) -> ProviderProfile:
    return _PROFILES.get(provider, _PROFILES["unknown"])


def get_compatibility_matrix() -> dict[str, ProviderProfile]:
    return dict(_PROFILES)


def get_compatibility_matrix_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile in _PROFILES.values():
        rows.append(
            {
                "provider": profile.name,
                "display_name": profile.display_name,
                "support_level": profile.support_level.value,
                "route": profile.route.value,
                "supports_reasoning_effort": profile.supports_reasoning_effort,
                "supports_thinking_budget": profile.supports_thinking_budget,
                "supports_prompt_caching": profile.supports_prompt_caching,
                "supports_vision": profile.supports_vision,
                "supports_service_tier": profile.supports_service_tier,
                "suggested_models": list(profile.suggested_models),
                "notes": profile.notes,
            }
        )
    return rows


def get_picker_seed_models() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile in _PROFILES.values():
        for model_id in profile.suggested_models:
            rows.append(
                {
                    "model_id": model_id,
                    "provider": profile.name,
                    "family": profile.display_name,
                    "support_level": profile.support_level.value,
                    "route": profile.route.value,
                }
            )
    return rows


def resolve_catalog_provider(model: str) -> Optional[str]:
    try:
        from bob.llm.catalog import get_catalog

        catalog = get_catalog()
        candidates = [model]
        if "/" in model:
            candidates.append(model.split("/", 1)[1])
        for candidate in candidates:
            row = catalog.get_model(candidate)
            if row and row.get("provider"):
                return str(row["provider"])
    except Exception:
        return None
    return None


def infer_provider(model: str, catalog_provider: Optional[str] = None) -> str:
    if catalog_provider:
        return _PROVIDER_ALIASES.get(catalog_provider, catalog_provider)

    if "/" in model:
        prefix = model.split("/", 1)[0].lower()
        if prefix in _PREFIX_PROVIDER_MAP:
            return _PREFIX_PROVIDER_MAP[prefix]

    bare = model.split("/", 1)[-1].lower()
    for prefix, provider in _MODEL_PATTERNS:
        if bare.startswith(prefix):
            return provider
    return "unknown"


def canonicalize_model_name(model: str, provider: str, route: ClientRoute) -> str:
    explicit_prefix = model.split("/", 1)[0].lower() if "/" in model else ""
    bare = model.split("/", 1)[-1]

    if route == ClientRoute.OPENAI_RESPONSES:
        return bare

    if explicit_prefix:
        return model

    if provider == "anthropic":
        return f"anthropic/{bare}"
    if provider == "gemini":
        return f"gemini/{bare}"
    if provider == "vertex_ai":
        return f"vertex_ai/{bare}"
    if provider == "openai":
        return f"openai/{bare}"
    if provider == "groq":
        return f"groq/{bare}"
    if provider == "mistral":
        return f"mistral/{bare}"
    if provider == "cohere":
        return f"cohere/{bare}"
    if provider == "together_ai":
        return f"together_ai/{bare}"
    if provider == "xai":
        return f"xai/{bare}"
    if provider == "openrouter":
        return f"openrouter/{bare}"
    if provider == "ollama":
        return f"ollama/{bare}"
    return model


def _route_for_model(provider: str, model: str) -> ClientRoute:
    bare = model.split("/", 1)[-1].lower()
    if provider == "openai":
        if bare == "codex-mini-latest" or any(bare.startswith(prefix) for prefix in _OPENAI_RESPONSES_PREFIXES):
            return ClientRoute.OPENAI_RESPONSES
        return ClientRoute.LITELLM_CHAT
    return get_provider_profile(provider).route


def get_model_compatibility(model: str, catalog_provider: Optional[str] = None) -> ModelCompatibility:
    provider = infer_provider(model, catalog_provider=catalog_provider or resolve_catalog_provider(model))
    route = _route_for_model(provider, model)
    profile = get_provider_profile(provider)
    canonical_model = canonicalize_model_name(model, provider, route)
    bare = model.split("/", 1)[-1]

    notes = [profile.notes] if profile.notes else []
    if provider == "unknown":
        notes.append("Model is not in Bob's compatibility matrix; runtime will fall back to LiteLLM.")
    elif profile.support_level == SupportLevel.CATALOG_ONLY:
        notes.append("Provider support is based on catalog entries and manual config rather than a first-class integration.")
    if provider == "gemini" and "/" not in model:
        notes.append("Bob added the gemini/ provider prefix automatically so GEMINI_API_KEY works without Vertex AI setup.")

    return ModelCompatibility(
        requested_model=model,
        canonical_model=canonical_model,
        bare_model=bare,
        provider=provider,
        route=route,
        support_level=profile.support_level,
        supports_reasoning_effort=profile.supports_reasoning_effort,
        supports_thinking_budget=profile.supports_thinking_budget,
        supports_prompt_caching=profile.supports_prompt_caching,
        supports_vision=profile.supports_vision,
        supports_service_tier=profile.supports_service_tier,
        notes=tuple(note for note in notes if note),
    )


def _first_present(names: Iterable[str], env: dict[str, str]) -> str:
    for name in names:
        value = env.get(name, "")
        if value:
            return value
    return ""


def _provider_config_as_dict(config: Any, provider: str) -> dict[str, Any]:
    try:
        provider_cfg = getattr(config, "providers", {}).get(provider)
    except Exception:
        provider_cfg = {}
    if provider_cfg is None:
        return {}
    if hasattr(provider_cfg, "model_dump"):
        return provider_cfg.model_dump()
    return dict(provider_cfg)


def resolve_provider_auth(
    model: str,
    config: Any,
    *,
    env: Optional[dict[str, str]] = None,
    compatibility: Optional[ModelCompatibility] = None,
) -> ResolvedProviderAuth:
    active_env = dict(os.environ if env is None else env)
    compat = compatibility or get_model_compatibility(model)
    profile = get_provider_profile(compat.provider)
    provider_cfg = _provider_config_as_dict(config, compat.provider)

    api_key = str(provider_cfg.get("api_key") or _first_present(profile.api_key_env_vars, active_env) or "")
    base_url = provider_cfg.get("base_url") or _first_present(profile.base_url_env_vars, active_env) or None
    used_global_fallback = False

    if not api_key:
        global_key = str(
            getattr(config, "api_key", "")
            or active_env.get("BOB_API_KEY", "")
            or ""
        )
        if global_key:
            api_key = global_key
            used_global_fallback = True

    if base_url is None:
        global_base_url = getattr(config, "base_url", None) or None
        if compat.provider == "openai":
            base_url = global_base_url
        elif global_base_url and global_base_url != "https://api.openai.com/v1":
            base_url = global_base_url
            used_global_fallback = True

    env_overrides: dict[str, str] = {}
    for field_name, env_name in profile.env_field_map.items():
        value = provider_cfg.get(field_name) or active_env.get(env_name, "")
        if value:
            env_overrides[env_name] = str(value)
    env_overrides.update({k: str(v) for k, v in (provider_cfg.get("env") or {}).items() if v})

    provider_kwargs: dict[str, Any] = {}
    for cfg_field, litellm_kwarg in profile.provider_kwargs_map.items():
        value = provider_cfg.get(cfg_field) or active_env.get(cfg_field.upper(), "")
        if value:
            provider_kwargs[litellm_kwarg] = value

    for key, value in (provider_cfg.get("headers") or {}).items():
        if value:
            provider_kwargs.setdefault("extra_headers", {})
            provider_kwargs["extra_headers"][str(key)] = str(value)

    for key, value in (provider_cfg.get("extra_kwargs") or {}).items():
        if value is not None:
            provider_kwargs[str(key)] = value

    missing: list[str] = []
    if profile.api_key_env_vars and not api_key and compat.provider not in ("vertex_ai", "unknown"):
        missing.append("api_key")
    if compat.provider == "vertex_ai":
        if not env_overrides.get("VERTEXAI_LOCATION") and not active_env.get("VERTEXAI_LOCATION", ""):
            missing.append("VERTEXAI_LOCATION")
        credentials_present = (
            env_overrides.get("GOOGLE_APPLICATION_CREDENTIALS")
            or active_env.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            or provider_kwargs.get("vertex_credentials")
        )
        if not credentials_present:
            missing.append("GOOGLE_APPLICATION_CREDENTIALS")

    return ResolvedProviderAuth(
        provider=compat.provider,
        api_key=api_key,
        base_url=base_url,
        provider_kwargs=provider_kwargs,
        env_overrides=env_overrides,
        missing=tuple(dict.fromkeys(missing)),
        used_global_fallback=used_global_fallback,
    )


def build_model_request_params(config: Any, compatibility: ModelCompatibility) -> dict[str, Any]:
    extra: dict[str, Any] = {}

    reasoning_effort = getattr(getattr(config, "reasoning_effort", None), "value", None)
    service_tier = getattr(getattr(config, "service_tier", None), "value", None)
    thinking_budget = int(getattr(config, "thinking_budget_tokens", 0) or 0)

    if compatibility.route == ClientRoute.OPENAI_RESPONSES:
        if compatibility.supports_reasoning_effort and reasoning_effort:
            extra["reasoning"] = {"effort": reasoning_effort}
        if compatibility.supports_service_tier and service_tier:
            extra["service_tier"] = service_tier
        return extra

    if compatibility.supports_prompt_caching:
        extra["prompt_caching"] = bool(getattr(config, "prompt_caching", True))

    if compatibility.supports_reasoning_effort and reasoning_effort:
        extra["reasoning_effort"] = reasoning_effort

    if compatibility.supports_service_tier and service_tier:
        extra["service_tier"] = service_tier

    if compatibility.supports_thinking_budget and thinking_budget > 0:
        extra["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

    return extra
