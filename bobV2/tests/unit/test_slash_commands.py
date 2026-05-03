from __future__ import annotations

from bob.tui.slash_commands import SlashCommand, parse_command


def test_parse_analytics_command_with_args() -> None:
    cmd, args = parse_command("/analytics tools")
    assert cmd == SlashCommand.ANALYTICS
    assert args == "tools"


def test_parse_tokens_command() -> None:
    cmd, args = parse_command("/tokens")
    assert cmd == SlashCommand.TOKENS
    assert args == ""
