from __future__ import annotations

from bob.core.turn import _format_missing_provider_auth_message


def test_kimi_missing_auth_message_lists_supported_env_vars() -> None:
    message = _format_missing_provider_auth_message(
        "kimi",
        ["api_key"],
        ("KIMI_API_KEY", "MOONSHOT_API_KEY", "OPENAI_API_KEY"),
    )

    assert "provider 'kimi'" in message
    assert "KIMI_API_KEY" in message
    assert "MOONSHOT_API_KEY" in message
    assert "OPENAI_API_KEY" in message
    assert "OpenAI-compatible endpoint" in message
