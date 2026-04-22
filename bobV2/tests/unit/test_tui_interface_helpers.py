from bob.tui.interface import Interface


def test_format_command_labels_cmd_wrapper() -> None:
    label, arg = Interface._format_command(["cmd.exe", "/C", "dir", "/b"])

    assert label == "Cmd"
    assert arg == "dir /b"


def test_format_command_labels_powershell_and_keeps_inner_flags() -> None:
    label, arg = Interface._format_command([
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-Command",
        "Get-ChildItem",
        "-Recurse",
        "-Depth",
        "3",
        "bobV2",
    ])

    assert label == "PowerShell"
    assert arg == "Get-ChildItem -Recurse -Depth 3 bobV2"


def test_format_command_labels_pwsh_c_wrapper() -> None:
    label, arg = Interface._format_command([
        "pwsh",
        "-c",
        "git",
        "status",
        "--short",
    ])

    assert label == "PowerShell"
    assert arg == "git status --short"


def test_input_box_dash_width_matches_shared_prompt_geometry() -> None:
    assert Interface._input_box_dash_width(120) == 117
    assert Interface._input_box_dash_width(40) == 37
