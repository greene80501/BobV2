from bob.core.tool_orchestrator import ToolOrchestrator


def test_normalize_windows_dir_flags_to_get_child_item() -> None:
    command, reason = ToolOrchestrator._normalize_windows_shell_command(
        ["dir", "/s", "/b", "bobV2"]
    )

    assert reason == "normalized_windows_dir_flags"
    assert command == ["Get-ChildItem", "-Recurse", "-Name", "bobV2"]


def test_normalize_windows_dir_flags_keeps_non_dir_commands() -> None:
    command, reason = ToolOrchestrator._normalize_windows_shell_command(
        ["Get-ChildItem", "-Recurse", "-Name", "bobV2"]
    )

    assert reason is None
    assert command == ["Get-ChildItem", "-Recurse", "-Name", "bobV2"]
