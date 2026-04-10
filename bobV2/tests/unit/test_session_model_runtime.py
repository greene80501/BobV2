from __future__ import annotations

from bob.config.schema import BobConfig
from bob.core.session import BobSession


class DummyBobClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class DummyLiteLLMClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _make_session(config: BobConfig) -> BobSession:
    session = BobSession.__new__(BobSession)
    session.config = config
    session._api_key = ""
    session._model_compatibility = None
    session._provider_auth = None
    return session


def test_session_uses_native_openai_client_for_gpt5(monkeypatch) -> None:
    import bob.client.openai_client as openai_client

    monkeypatch.setattr(openai_client, "BobClient", DummyBobClient)
    config = BobConfig.model_validate(
        {
            "model": "gpt-5.1-codex-mini",
            "providers": {
                "openai": {
                    "api_key": "openai-key",
                    "base_url": "https://api.openai.example/v1",
                }
            },
        }
    )
    session = _make_session(config)

    client = session._make_client(config.model)

    assert isinstance(client, DummyBobClient)
    assert client.kwargs["api_key"] == "openai-key"
    assert client.kwargs["model"] == "gpt-5.1-codex-mini"
    assert client.kwargs["base_url"] == "https://api.openai.example/v1"
    assert session._model_compatibility.provider == "openai"


def test_session_uses_litellm_for_anthropic(monkeypatch) -> None:
    import bob.llm.client as litellm_client

    monkeypatch.setattr(litellm_client, "LiteLLMClient", DummyLiteLLMClient)
    config = BobConfig.model_validate(
        {
            "model": "claude-3.5-sonnet",
            "providers": {
                "anthropic": {
                    "api_key": "anthropic-key",
                }
            },
        }
    )
    session = _make_session(config)

    client = session._make_client(config.model)

    assert isinstance(client, DummyLiteLLMClient)
    assert client.kwargs["api_key"] == "anthropic-key"
    assert client.kwargs["model"] == "anthropic/claude-3.5-sonnet"
    assert client.kwargs["env_overrides"] == {}
    assert session._model_compatibility.provider == "anthropic"


def test_session_passes_vertex_env_overrides_to_litellm(monkeypatch) -> None:
    import bob.llm.client as litellm_client

    monkeypatch.setattr(litellm_client, "LiteLLMClient", DummyLiteLLMClient)
    config = BobConfig.model_validate(
        {
            "model": "vertex_ai/gemini-2.5-pro",
            "providers": {
                "vertex_ai": {
                    "project": "proj-123",
                    "location": "us-central1",
                    "credentials_path": "C:/creds.json",
                }
            },
        }
    )
    session = _make_session(config)

    client = session._make_client(config.model)

    assert isinstance(client, DummyLiteLLMClient)
    assert client.kwargs["model"] == "vertex_ai/gemini-2.5-pro"
    assert client.kwargs["env_overrides"]["VERTEXAI_PROJECT"] == "proj-123"
    assert client.kwargs["env_overrides"]["VERTEXAI_LOCATION"] == "us-central1"
    assert client.kwargs["env_overrides"]["GOOGLE_APPLICATION_CREDENTIALS"] == "C:\\creds.json"


def test_describe_model_runtime_reports_missing_auth(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("BOB_API_KEY", raising=False)
    config = BobConfig(model="gemini/gemini-2.5-pro")
    session = _make_session(config)

    runtime = session.describe_model_runtime(config.model)

    assert runtime["provider"] == "gemini"
    assert runtime["route"] == "litellm_chat"
    assert "api_key" in runtime["missing_auth"]
